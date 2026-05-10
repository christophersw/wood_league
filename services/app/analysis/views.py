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
    2026-05-10: Task C1 — refactor status() to overview cards; drop recent_jobs;
        rename queue_partial to overview_partial serving _overview_cards.html.
    2026-05-08: Added file header to meet documentation standards
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from . import services

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
    assembles the ``engine_rows`` list consumed by ``_overview_cards.html``.
    Does NOT include recent_jobs — that table lives on the per-engine queue page.

    Returns:
        dict: Keys are ``engine_rows`` (list of per-engine dicts) and
              ``workers`` (list of worker-heartbeat dicts).
    """
    by_engine = services.queue_by_engine()
    engines = ["stockfish", "lc0"]
    statuses = ["pending", "submitted", "running", "completed"]

    rows: list[dict] = []
    for eng in engines:
        health, error = services.runpod_health(eng)
        row: dict = {"name": eng, "runpod": health, "runpod_error": error}
        for s in statuses:
            row[s] = _engine_metric(by_engine, eng, s)
        rows.append(row)

    return {
        "engine_rows": rows,
        "workers": services.worker_heartbeats(),
    }


@_admin_login_required
@require_GET
def status(request: HttpRequest) -> HttpResponse:
    """Render the analysis overview: engine summary cards + worker status.

    Args:
        request: The incoming HTTP GET request.

    Returns:
        HttpResponse: Rendered ``analysis/status.html`` with overview context.
    """
    return render(request, "analysis/status.html", _queue_context())


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
