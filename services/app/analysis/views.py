"""
Title: views.py — Analysis admin views
Description:
    Provides views for the analysis admin section. Restricted to admin/staff
    users. Contains the RunPod start hook and access-control helpers shared
    across the analysis module.

Changelog:
    2026-05-22 (#200): Remove queue views (queues_summary, overview_partial,
        _queue_context, _engine_metric) and their unused imports now that the
        queue pages have been retired.
    2026-05-14 (#106): Remove legacy diagnostics_view, _recent_failures
        helper, and re-exports from dashboard_helpers — superseded by the
        consolidated /admin/dashboard/ partial views.
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

from django.conf import settings as django_settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
)
from django.views.decorators.http import require_POST

from app.runpod_client import start_pod

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
