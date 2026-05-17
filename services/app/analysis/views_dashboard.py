"""
Title: views_dashboard.py — Worker dashboard views
Description:
    Hosts the consolidated /admin/dashboard/ shell view plus the six
    HTMX-polled partials (banner, workers, queues, throughput, recent,
    failures). Replaces the legacy /admin/diagnostics/ page.

Changelog:
    2026-05-14 (#106): Initial wire-up — stub partials, no real data yet.
    2026-05-14 (#106): Banner + workers partials now render live data.
    2026-05-14 (#106): Queues + throughput partials now render live data.
    2026-05-14 (#106): Recent partial now renders live data.
    2026-05-14 (#106): Failures partial now renders live data.
    2026-05-14 (#106): Coerce naive datetimes in banner + workers views.
    2026-05-14: Add ``dashboard_logs`` partial listing recent worker log
        uploads with per-row download links.
    2026-05-17 (#128): Rebuild ``dashboard_workers`` — filter stale workers,
        flag live vs reporting, emit per-engine cards with batch progress,
        billable time/game, and recent games.
"""
from __future__ import annotations

from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone


def _aware(dt):
    """Return a TZ-aware datetime; coerce naive inputs to the current TZ.

    Defensive helper for legacy DB rows that pre-date Django ``USE_TZ=True``.
    Subtracting a naive datetime from a TZ-aware ``timezone.now()`` raises
    ``TypeError``, so we coerce naive values into the current timezone.

    Args:
        dt: A ``datetime`` or ``None``.

    Returns:
        A TZ-aware ``datetime`` (or ``None`` if ``dt`` was ``None``).
    """
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@staff_member_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Render the dashboard shell page.

    The shell page contains HTMX wrappers that each poll a partial view
    for live data. The shell itself carries no data — partials are the
    sole source of truth so a slow query in one section never blocks
    the rest of the page.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML response for ``analysis/dashboard.html``.
    """
    return render(request, "analysis/dashboard.html", {})


@staff_member_required
def dashboard_banner(request: HttpRequest) -> HttpResponse:
    """Render the health-banner partial.

    Reports ``healthy_workers / total_workers``, ``pending_jobs`` across
    all engines, and ``jobs_completed_today`` (UTC midnight rollover).
    Banner-level "health" is the worst liveness state across workers.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_banner.html``.
    """
    from analysis.models import AnalysisJob, WorkerHeartbeat
    from analysis.dashboard_helpers import _liveness_for

    now = timezone.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    workers = list(WorkerHeartbeat.objects.all())
    livenesses = [_liveness_for(now - _aware(w.last_seen)) for w in workers]
    healthy = sum(1 for v in livenesses if v == "healthy")

    if not workers or "stale" in livenesses:
        banner_state = "stale"
    elif "warning" in livenesses:
        banner_state = "warning"
    else:
        banner_state = "healthy"

    pending = AnalysisJob.objects.filter(
        status__in=[AnalysisJob.STATUS_PENDING, AnalysisJob.STATUS_SUBMITTED],
    ).count()
    done_today = AnalysisJob.objects.filter(
        status=AnalysisJob.STATUS_COMPLETED,
        completed_at__gte=midnight,
    ).count()

    context = {
        "healthy_workers": healthy,
        "total_workers": len(workers),
        "pending": pending,
        "done_today": done_today,
        "banner_state": banner_state,
    }
    return render(request, "analysis/_dash_banner.html", context)


@staff_member_required
def dashboard_workers(request: HttpRequest) -> HttpResponse:
    """Render the workers partial — one card per live/reporting worker.

    Workers whose last heartbeat is older than ``STALE_DROP_SECONDS`` are
    dropped entirely. Survivors are flagged ``"live"`` (heartbeat within
    ``LIVE_WINDOW_SECONDS``) or ``"reporting"``. Each card carries
    per-engine timing (time/ply, time/game) derived from completed
    ``AnalysisJob`` rows, a batch-progress fraction (N/M from the
    heartbeat), a billable time/game figure, and the worker's 10 most
    recently completed games.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_workers.html``.
    """
    from analysis.models import WorkerHeartbeat
    from analysis.dashboard_helpers import (
        _batch_billable_per_game,
        _worker_engine_metrics,
        _worker_live_state,
        _worker_recent_games,
    )

    now = timezone.now()
    cards: list[dict[str, Any]] = []
    for w in WorkerHeartbeat.objects.order_by("-last_seen"):
        last_seen = _aware(w.last_seen)
        delta_seen = now - last_seen if last_seen else None
        live_state = _worker_live_state(delta_seen)
        if live_state is None:
            continue  # stale-dropped or never seen

        session_started_at = _aware(w.session_started_at)
        billable = _batch_billable_per_game(
            session_started_at, last_seen, w.batch_processed
        )

        batch_total = w.batch_total
        batch_processed = w.batch_processed or 0
        if batch_total and batch_total > 0:
            batch_percent = round(
                min(batch_processed / batch_total, 1.0) * 100, 2
            )
        else:
            batch_percent = None

        cards.append({
            "worker_id": w.worker_id,
            "engine": w.engine,
            "status_message": w.status_message,
            "live_state": live_state,
            "seconds_since_seen": (
                int(delta_seen.total_seconds()) if delta_seen else None
            ),
            "engine_rows": _worker_engine_metrics(w.worker_id),
            "batch_total": batch_total,
            "batch_processed": batch_processed,
            "batch_percent": batch_percent,
            "billable_per_game": billable,
            "recent_games": _worker_recent_games(w.worker_id, limit=10),
        })
    return render(request, "analysis/_dash_workers.html", {"cards": cards})


@staff_member_required
def dashboard_queues(request: HttpRequest) -> HttpResponse:
    """Render the queues partial.

    For each known engine, show pending/running counts, the per-minute
    completion rate over the last 10 minutes, and an ETA to drain.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_queues.html``.
    """
    from analysis.models import AnalysisJob
    from analysis.dashboard_helpers import _eta_for, _rate_per_min

    rows: list[dict[str, Any]] = []
    for engine in ("stockfish", "lc0"):
        pending = AnalysisJob.objects.filter(
            engine=engine,
            status__in=[AnalysisJob.STATUS_PENDING, AnalysisJob.STATUS_SUBMITTED],
        ).count()
        running = AnalysisJob.objects.filter(
            engine=engine, status=AnalysisJob.STATUS_RUNNING,
        ).count()
        rate = _rate_per_min(engine)
        rows.append({
            "engine": engine,
            "pending": pending,
            "running": running,
            "rate": round(rate, 2),
            "eta": _eta_for(pending, rate),
        })
    return render(request, "analysis/_dash_queues.html", {"rows": rows})


@staff_member_required
def dashboard_throughput(request: HttpRequest) -> HttpResponse:
    """Render the throughput partial (1h / 6h / 24h windows).

    Reuses :func:`analysis.dashboard_helpers._engine_throughput_row` to
    compute each engine's completed count and p50/p95 durations within
    each window.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_throughput.html``.
    """
    from analysis.dashboard_helpers import _engine_throughput_row

    engines = ("stockfish", "lc0")
    windows = (1, 6, 24)
    rows: list[dict[str, Any]] = []
    for engine in engines:
        window_data = {h: _engine_throughput_row(engine, h) for h in windows}
        twenty_four = window_data[24]
        rows.append({
            "engine": engine,
            "h1": window_data[1]["completed"],
            "h6": window_data[6]["completed"],
            "h24": window_data[24]["completed"],
            "p50": twenty_four["p50_seconds"],
            "p95": twenty_four["p95_seconds"],
        })
    return render(request, "analysis/_dash_throughput.html", {"rows": rows})


@staff_member_required
def dashboard_recent(request: HttpRequest) -> HttpResponse:
    """Render the recently-completed partial.

    Groups the most recent completed jobs by game (last 25 games) and
    shows per-engine runtime side by side, with a link to each game's
    analysis page.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_recent.html``.
    """
    from analysis.dashboard_helpers import _group_recent_by_game

    rows = _group_recent_by_game(limit=25)
    for row in rows:
        row["game_url"] = (
            reverse("games:analysis", kwargs={"slug": row["game_slug"]})
            if row["game_slug"] else None
        )
    return render(request, "analysis/_dash_recent.html", {"rows": rows})


@staff_member_required
def dashboard_failures(request: HttpRequest) -> HttpResponse:
    """Render the recent-failures partial.

    Surfaces the 10 most-recently-failed analysis jobs, each linked to
    the matching worker log upload when one is available.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_failures.html``.
    """
    from analysis.dashboard_helpers import _build_failure_row
    from analysis.models import AnalysisJob

    failures = (
        AnalysisJob.objects
        .filter(status=AnalysisJob.STATUS_FAILED)
        .order_by("-completed_at", "-last_error_at", "-created_at")[:10]
    )
    rows = [_build_failure_row(job) for job in failures]
    return render(request, "analysis/_dash_failures.html", {"rows": rows})


@staff_member_required
def dashboard_logs(request: HttpRequest) -> HttpResponse:
    """Render the worker-logs partial.

    Lists the 20 most recently uploaded :class:`WorkerLogUpload` rows
    with a per-row Download link that 302-redirects to a short-lived
    presigned URL via the existing admin view.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_logs.html``.
    """
    from api.models import WorkerLogUpload

    uploads = (
        WorkerLogUpload.objects
        .select_related("worker")
        .order_by("-uploaded_at")[:20]
    )
    rows: list[dict[str, Any]] = []
    for upload in uploads:
        note = upload.note or ""
        first_line = note.splitlines()[0].strip() if note else ""
        rows.append({
            "id": upload.pk,
            "worker_name": upload.worker.worker_name,
            "uploaded_at": upload.uploaded_at,
            "reason": upload.reason,
            "size_kb": round(upload.size_bytes / 1024, 1),
            "note_preview": first_line,
            "download_url": reverse(
                "admin:api_workerlogupload_download", args=[upload.pk]
            ),
        })
    return render(request, "analysis/_dash_logs.html", {"rows": rows})
