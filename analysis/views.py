"""Views for displaying game analysis status and job queue metrics."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import services

_admin_required = user_passes_test(lambda u: u.role == "admin")


def _admin_login_required(view):
    """Decorator to require both login and admin role."""
    return login_required(_admin_required(view))


def _engine_metric(rows: list[dict], engine: str, status: str) -> int:
    """Extract job count for a specific engine and status from aggregated data."""
    for r in rows:
        if r["engine"] == engine and r["status"] == status:
            return r["count"]
    return 0


def _queue_context() -> dict:
    """Build context data for analysis queue status display including worker health."""
    totals = services.queue_totals()
    by_engine = services.queue_by_engine()
    total = sum(totals.values())
    completed = totals.get("completed", 0)

    statuses = ["pending", "submitted", "running", "completed", "failed"]
    engines = ["stockfish", "lc0"]

    engine_rows = []
    for eng in engines:
        health, error = services.runpod_health(eng)
        row = {"name": eng, "runpod": health, "runpod_error": error}
        for s in statuses:
            row[s] = _engine_metric(by_engine, eng, s)
        engine_rows.append(row)

    return {
        "totals": totals,
        "total": total,
        "completed": completed,
        "progress_pct": round(completed / total * 100, 1) if total else 0,
        "engine_rows": engine_rows,
        "workers": services.worker_heartbeats(),
    }


@_admin_login_required
@require_GET
def status(request: HttpRequest) -> HttpResponse:
    """Render the analysis status dashboard with queue and worker metrics."""
    jobs = services.recent_jobs(100)
    return render(request, "analysis/status.html", {
        "jobs": jobs,
        **_queue_context(),
    })


@_admin_login_required
@require_GET
def queue_partial(request: HttpRequest) -> HttpResponse:
    """Render an HTMX partial showing the current analysis queue snapshot."""
    return render(request, "analysis/_queue_partial.html", _queue_context())
