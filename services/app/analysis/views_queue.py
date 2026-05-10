"""
Title: views_queue.py — Per-engine queue detail pages
Description: Admin-only views for /queue/stockfish/ and /queue/lc0/. Renders
    Pending (with bulk-submit checkbox UI), Active (running+submitted, read-only),
    and Recent (last 50 completed/failed) sections. Also includes the bulk
    RunPod submit endpoint (POST /queue/<engine>/submit/).
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
    2026-05-10: Added queue_submit view — Task B2 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import AnalysisJob
from .services.runpod_dispatch import submit_job_to_runpod

_ENGINES = {"stockfish", "lc0"}


def _admin_required(view):
    """Decorator requiring login and admin role.

    Wraps a view function so that only authenticated users with role='admin'
    can access it. Unauthenticated users are redirected to the login page;
    non-admins receive a 403 redirect via user_passes_test.

    Args:
        view: The Django view function to protect.

    Returns:
        callable: The decorated view function.
    """
    return login_required(user_passes_test(lambda u: u.role == "admin")(view))


def _queue_context(engine: str) -> dict:
    """Build context dict for one engine's queue detail page.

    Fetches pending, active (running + submitted), and recent
    (last 50 completed/failed) jobs for the given engine.

    Args:
        engine: The engine name string, either 'stockfish' or 'lc0'.

    Returns:
        dict: Context with keys 'engine', 'pending', 'active', 'recent'.
    """
    pending = list(
        AnalysisJob.objects
        .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
        .select_related("game")
        .order_by("-priority", "created_at")
    )
    active = list(
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_RUNNING, AnalysisJob.STATUS_SUBMITTED,
        ])
        .select_related("game")
        .order_by("-started_at")
    )
    recent = list(
        AnalysisJob.objects
        .filter(engine=engine, status__in=[
            AnalysisJob.STATUS_COMPLETED, AnalysisJob.STATUS_FAILED,
        ])
        .select_related("game")
        .order_by("-completed_at")[:50]
    )
    return {
        "engine": engine,
        "pending": pending,
        "active": active,
        "recent": recent,
    }


@_admin_required
@require_GET
def queue_stockfish(request: HttpRequest) -> HttpResponse:
    """Render the Stockfish engine queue detail page at /admin/queue/stockfish/.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        HttpResponse: Rendered analysis/queue.html with stockfish queue data.
    """
    return render(request, "analysis/queue.html", _queue_context("stockfish"))


@_admin_required
@require_GET
def queue_lc0(request: HttpRequest) -> HttpResponse:
    """Render the lc0 engine queue detail page at /admin/queue/lc0/.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        HttpResponse: Rendered analysis/queue.html with lc0 queue data.
    """
    return render(request, "analysis/queue.html", _queue_context("lc0"))


@_admin_required
@require_POST
def queue_submit(request: HttpRequest, engine: str) -> HttpResponse:
    """Submit selected pending jobs for `engine` to RunPod.

    Per-job transaction with SELECT FOR UPDATE SKIP LOCKED. Successes go to
    `submitted` with `runpod_job_id`. Failures keep `pending` and record
    `last_error` / `last_error_at`. Jobs not found / not pending / wrong engine
    are counted as skipped.

    Args:
        request: The incoming HTTP POST request. Must contain `job_ids` as a
            list of integer job primary keys.
        engine: Engine name from URL (e.g. 'stockfish' or 'lc0').

    Returns:
        HttpResponse: Rendered partial template with submit result counts and
            refreshed pending job list, suitable for HTMX consumption.
        HttpResponseBadRequest: If `engine` is not a recognised engine name.
    """
    if engine not in _ENGINES:
        return HttpResponseBadRequest("invalid engine")

    raw_ids = request.POST.getlist("job_ids")
    job_ids: list[int] = []
    for raw in raw_ids:
        try:
            job_ids.append(int(raw))
        except ValueError:
            continue

    submitted = skipped = failed = 0
    errors: list[dict] = []

    for jid in job_ids:
        with transaction.atomic():
            job = (
                AnalysisJob.objects
                .select_for_update(skip_locked=True)
                .filter(id=jid, engine=engine, status=AnalysisJob.STATUS_PENDING)
                .select_related("game")
                .first()
            )
            if job is None:
                skipped += 1
                continue
            try:
                runpod_id = submit_job_to_runpod(job)
            except Exception as exc:  # noqa: BLE001 — record any failure for retry
                job.last_error = str(exc)[:1000]
                job.last_error_at = timezone.now()
                job.save(update_fields=["last_error", "last_error_at"])
                failed += 1
                errors.append({"id": jid, "error": str(exc)[:200]})
                continue
            job.status = AnalysisJob.STATUS_SUBMITTED
            job.runpod_job_id = runpod_id
            job.submitted_at = timezone.now()
            job.last_error = None
            job.last_error_at = None
            job.save(update_fields=[
                "status", "runpod_job_id", "submitted_at",
                "last_error", "last_error_at",
            ])
            submitted += 1

    context = {
        "engine": engine,
        "submitted": submitted,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
        **_queue_context(engine),
    }
    return render(request, "analysis/_queue_submit_result.html", context)
