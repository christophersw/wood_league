"""
Title: views_dashboard.py — Worker dashboard views
Description:
    Hosts the consolidated /admin/dashboard/ shell view plus the six
    HTMX-polled partials (banner, workers, queues, throughput, recent,
    failures). Replaces the legacy /admin/diagnostics/ page.

Changelog:
    2026-05-14 (#106): Initial wire-up — stub partials, no real data yet.
    2026-05-14 (#106): Banner + workers partials now render live data.
"""
from __future__ import annotations

from typing import Any

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone


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
    livenesses = [_liveness_for(now - w.last_seen) for w in workers]
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
    """Render the workers partial (one card per WorkerHeartbeat).

    Each card carries: status dot color (from liveness bucket), seconds
    since last_seen, current game (linked when resolvable), jobs
    completed/failed counters, uptime, engine, hardware footer.

    Args:
        request: The incoming Django HTTP request.

    Returns:
        Rendered HTML for ``analysis/_dash_workers.html``.
    """
    from analysis.models import WorkerHeartbeat
    from analysis.dashboard_helpers import (
        _format_memory_mb,
        _format_uptime,
        _game_link_for,
        _liveness_for,
    )

    now = timezone.now()
    cards: list[dict[str, Any]] = []
    for w in WorkerHeartbeat.objects.order_by("-last_seen"):
        delta_seen = now - w.last_seen if w.last_seen else None
        uptime = now - w.started_at if w.started_at else None
        game_label, game_url = _game_link_for(w.current_game_id)
        cards.append({
            "worker_id": w.worker_id,
            "engine": w.engine,
            "status": w.status,
            "status_message": w.status_message,
            "liveness": _liveness_for(delta_seen),
            "seconds_since_seen": int(delta_seen.total_seconds()) if delta_seen else None,
            "current_game_label": game_label,
            "current_game_url": game_url,
            "jobs_completed": w.jobs_completed,
            "jobs_failed": w.jobs_failed,
            "uptime": _format_uptime(uptime),
            "cpu_model": w.cpu_model or "—",
            "cpu_cores": w.cpu_cores,
            "memory": _format_memory_mb(w.memory_mb),
        })
    return render(request, "analysis/_dash_workers.html", {"cards": cards})


@staff_member_required
def dashboard_queues(request: HttpRequest) -> HttpResponse:
    """Render the queues partial (stub)."""
    return render(request, "analysis/_dash_queues.html", {})


@staff_member_required
def dashboard_throughput(request: HttpRequest) -> HttpResponse:
    """Render the throughput partial (stub)."""
    return render(request, "analysis/_dash_throughput.html", {})


@staff_member_required
def dashboard_recent(request: HttpRequest) -> HttpResponse:
    """Render the recently-completed partial (stub)."""
    return render(request, "analysis/_dash_recent.html", {})


@staff_member_required
def dashboard_failures(request: HttpRequest) -> HttpResponse:
    """Render the recent-failures partial (stub)."""
    return render(request, "analysis/_dash_failures.html", {})
