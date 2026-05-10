"""
Title: views_queue.py — Per-engine queue detail pages
Description: Admin-only views for /queue/stockfish/ and /queue/lc0/. Renders
    Pending (with bulk-submit checkbox UI), Active (running+submitted, read-only),
    and Recent (last 50 completed/failed) sections.
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .models import AnalysisJob


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
