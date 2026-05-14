"""
Title: views.py — Game analysis status dashboard and queue monitoring
Description:
    Provides views for displaying analysis job queue status, including job counts
    by engine and status, RunPod worker health checks, and worker heartbeat
    tracking. Restricted to admin users.

    The /analysis/ route now renders an overview page with per-engine summary
    cards linking to the per-engine queue detail pages. The old combined
    queue+recent-jobs view has been replaced (Task C1, scrap-dispatchers plan).

Changelog:
    2026-05-14 (#86): Add diagnostics_view + helpers for 24h throughput and
        recent-failures admin page.
    2026-05-11: Task 9 — extend _queue_context() with pending_high, failed_24h,
        and worker_last_seen for the rebuilt queues_summary.html engine cards.
    2026-05-11: Task 4 — remove backward-compat alias status = queues_summary
        now that URL route is renamed to queues_summary.
    2026-05-11: Task 5 — rename status() → queues_summary(); point at
        analysis/queues_summary.html.
    2026-05-10: Task C1 — refactor status() to overview cards; drop recent_jobs;
        rename queue_partial to overview_partial serving _overview_cards.html.
    2026-05-08: Added file header to meet documentation standards
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.shortcuts import render
from django.utils import timezone
from django.utils.timesince import timesince
from django.views.decorators.http import require_GET, require_POST

from app.runpod_client import start_pod

from .models import AnalysisJob, WorkerHeartbeat
from . import services
from analysis.dashboard_helpers import (
    _build_failure_row,
    _engine_throughput_row,  # noqa: F401 — re-exported for backwards compat
    _failure_timestamp,
    _percentile,  # noqa: F401 — re-exported for backwards compat
    _throughput_for_window,
    _worker_log_url_for,  # noqa: F401 — re-exported for backwards compat
)

_LOGGER = logging.getLogger(__name__)

_admin_required = user_passes_test(lambda u: u.role == "admin")


def _admin_login_required(view):
    """Decorate a view to require both login and admin role.

    Args:
        view: The view function to protect.

    Returns:
        Callable: The wrapped view enforcing login + admin checks.
    """
    return login_required(_admin_required(view))


def _engine_metric(rows: list[dict], engine: str, status: str) -> int:
    """Extract the job count for a specific engine and status from aggregated data.

    Args:
        rows: List of dicts with keys ``engine``, ``status``, and ``count``
              as returned by ``services.queue_by_engine()``.
        engine: Engine name to filter on (e.g. ``"stockfish"``).
        status: Job status to filter on (e.g. ``"pending"``).

    Returns:
        int: The count for the given engine+status combination, or 0 if absent.
    """
    for r in rows:
        if r["engine"] == engine and r["status"] == status:
            return r["count"]
    return 0


def _queue_context() -> dict:
    """Build context for the analysis overview: per-engine summary + workers.

    Fetches live queue counts and RunPod health for each engine, then
    assembles the ``engine_rows`` list consumed by ``queues_summary.html``.
    Does NOT include recent_jobs — that table lives on the per-engine queue page.

    Extended in Task 9 to include ``pending_high`` (count of pending jobs at
    HIGH priority or above), ``failed_24h`` (failed jobs in the last 24 hours),
    and ``worker_last_seen`` (the most recent WorkerHeartbeat datetime for each
    engine, for display via Django's ``naturaltime`` template filter).

    Returns:
        dict: Keys are ``engine_rows`` (list of per-engine dicts) and
              ``workers`` (list of worker-heartbeat dicts).
              Each engine dict contains: ``name``, ``pending``, ``submitted``,
              ``running``, ``completed``, ``runpod``, ``runpod_error``,
              ``pending_high``, ``failed_24h``, ``worker_last_seen``.
    """
    by_engine = services.queue_by_engine()
    engines = ["stockfish", "lc0"]
    statuses = ["pending", "submitted", "running", "completed"]
    cutoff_24h = timezone.now() - timedelta(hours=24)

    rows: list[dict] = []
    for eng in engines:
        health, error = services.runpod_health(eng)
        row: dict = {"name": eng, "runpod": health, "runpod_error": error}
        for s in statuses:
            row[s] = _engine_metric(by_engine, eng, s)

        # High-priority pending count (Task 9)
        row["pending_high"] = AnalysisJob.objects.filter(
            engine=eng,
            status=AnalysisJob.STATUS_PENDING,
            priority__gte=AnalysisJob.PRIORITY_HIGH,
        ).count()

        # Failed jobs in last 24 hours (Task 9)
        row["failed_24h"] = AnalysisJob.objects.filter(
            engine=eng,
            status=AnalysisJob.STATUS_FAILED,
            completed_at__gte=cutoff_24h,
        ).count()

        # Most recent worker heartbeat timestamp for this engine (Task 9)
        # Pre-format as a human-readable string so the template needs no extra
        # tag library (django.contrib.humanize is not installed).
        heartbeat = (
            WorkerHeartbeat.objects
            .filter(engine=eng)
            .order_by("-last_seen")
            .first()
        )
        if heartbeat:
            row["worker_last_seen"] = timesince(heartbeat.last_seen) + " ago"
        else:
            row["worker_last_seen"] = None

        rows.append(row)

    return {
        "engine_rows": rows,
        "workers": services.worker_heartbeats(),
    }


@_admin_login_required
@require_GET
def queues_summary(request: HttpRequest) -> HttpResponse:
    """Render the analysis queues summary: per-engine cards + worker status.

    This is the renamed version of the former ``status`` view, pointing at the
    new ``analysis/queues_summary.html`` template.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        HttpResponse: Rendered ``analysis/queues_summary.html`` with overview context.
    """
    context = _queue_context()
    context["runpod_enabled"] = bool(getattr(django_settings, "RUNPOD_ENABLED", False))
    context["runpod_worker_pod_id"] = getattr(django_settings, "RUNPOD_WORKER_POD_ID", "")
    return render(request, "analysis/queues_summary.html", context)


def _recent_failures(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent failed analysis jobs as template-friendly dicts.

    Failures are ordered by ``COALESCE(completed_at, last_error_at,
    created_at) DESC`` and capped at ``limit`` rows.

    Args:
        limit: Maximum number of failures to return. Defaults to 50.

    Returns:
        A list of dicts produced by :func:`_build_failure_row`.
    """
    failures_qs = (
        AnalysisJob.objects
        .filter(status=AnalysisJob.STATUS_FAILED)
        .select_related("game")
    )
    jobs = list(failures_qs)
    jobs.sort(key=_failure_timestamp, reverse=True)
    trimmed = jobs[:limit]
    return [_build_failure_row(job) for job in trimmed]


@_admin_login_required
@require_GET
def diagnostics_view(request: HttpRequest) -> HttpResponse:
    """Render the staff-only diagnostics admin page.

    Displays a 24-hour throughput summary per engine and a table of the
    most recent failed analysis jobs with deep links to the matching
    worker log uploads when available.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        Rendered ``analysis/diagnostics.html`` response.
    """
    context = {
        "throughput_rows": _throughput_for_window(hours=24),
        "failure_rows": _recent_failures(limit=50),
        "window_hours": 24,
    }
    return render(request, "analysis/diagnostics.html", context)


@_admin_login_required
@require_GET
def overview_partial(request: HttpRequest) -> HttpResponse:
    """Render the HTMX overview-cards partial for auto-refresh polling.

    This endpoint is polled every 30 s by the ``#engine-cards`` container
    on the overview page. It returns only the cards fragment, not the full page.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        HttpResponse: Rendered ``analysis/_overview_cards.html`` fragment.
    """
    return render(request, "analysis/_overview_cards.html", _queue_context())


def _runpod_creds() -> tuple[str, str]:
    """Return the configured RunPod (pod_id, api_key) pair from Django settings.

    Returns:
        tuple[str, str]: ``(RUNPOD_WORKER_POD_ID, RUNPOD_API_KEY)``. Either
            may be the empty string when not configured.
    """
    pod_id = getattr(django_settings, "RUNPOD_WORKER_POD_ID", "") or ""
    api_key = getattr(django_settings, "RUNPOD_API_KEY", "") or ""
    return pod_id, api_key


@login_required
@require_POST
def runpod_start_view(request: HttpRequest) -> HttpResponse:
    """Start the configured RunPod worker pod (admin-only).

    Gated by ``settings.RUNPOD_ENABLED`` — returns 404 when False so the
    endpoint is invisible in non-RunPod deployments. Staff-only:
    authenticated non-staff users receive 403. Credentials missing
    (empty pod id or api key) returns a 400 JSON response. On RunPod
    failure (network or non-2xx) returns 502 with the structured result.

    Args:
        request: The incoming HTTP POST request. CSRF-protected.

    Returns:
        JsonResponse: ``{"ok", "status_code", "message"}``. Status code is
            200 on success, 400 when creds are missing, 502 when RunPod
            returns a failure.

    Side effects:
        Logs the attempt at INFO with the requesting username and the
        target pod id (the api key is never logged).
    """
    if not getattr(django_settings, "RUNPOD_ENABLED", False):
        raise Http404("RunPod start endpoint disabled")
    if not request.user.is_staff:
        return HttpResponseForbidden("staff only")

    pod_id, api_key = _runpod_creds()
    if not pod_id or not api_key:
        return JsonResponse(
            {"ok": False, "status_code": 0, "message": "RunPod credentials not configured"},
            status=400,
        )

    _LOGGER.info(
        "runpod start_pod requested by user=%s pod=%s",
        getattr(request.user, "email", request.user.get_username()),
        pod_id,
    )
    result = start_pod(pod_id, api_key)
    http_status = 200 if result["ok"] else 502
    return JsonResponse(result, status=http_status)
