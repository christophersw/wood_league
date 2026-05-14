"""
Title: views_dashboard.py — Worker dashboard views
Description:
    Hosts the consolidated /admin/dashboard/ shell view plus the six
    HTMX-polled partials (banner, workers, queues, throughput, recent,
    failures). Replaces the legacy /admin/diagnostics/ page.

Changelog:
    2026-05-14 (#106): Initial wire-up — stub partials, no real data yet.
"""
from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


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
    """Render the health-banner partial (stub)."""
    return render(request, "analysis/_dash_banner.html", {})


@staff_member_required
def dashboard_workers(request: HttpRequest) -> HttpResponse:
    """Render the workers partial (stub)."""
    return render(request, "analysis/_dash_workers.html", {})


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
