"""
Title: urls.py — URL routing for analysis module views
Description:
    Defines URL patterns for the consolidated worker dashboard and the
    per-engine queues management pages.

Changelog:
    2026-05-14 (#106): Add /dashboard/ + 6 HTMX partial routes; convert
        /diagnostics/ to a redirect to /dashboard/.
    2026-05-14 (#101): Remove legacy /queues/<engine>/submit/ route.
    2026-05-14 (#86): Add diagnostics/ route.
    2026-05-11: Task 4 — rename URL family to /admin/queues/ (plural).
    2026-05-08: Added file header.
"""
from django.urls import path
from django.views.generic import RedirectView

from . import views, views_dashboard, views_queue

app_name = "analysis"

urlpatterns = [
    path("queues/", views.queues_summary, name="queues_summary"),
    path("queues/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queues/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    path("queues/<str:engine>/reorder/", views_queue.queue_reorder, name="queue_reorder"),
    path("runpod/start/", views.runpod_start_view, name="runpod_start"),

    # Dashboard (consolidated worker observability).
    path("dashboard/", views_dashboard.dashboard, name="dashboard"),
    path("dashboard/banner/", views_dashboard.dashboard_banner, name="dash_banner"),
    path("dashboard/workers/", views_dashboard.dashboard_workers, name="dash_workers"),
    path("dashboard/queues/", views_dashboard.dashboard_queues, name="dash_queues"),
    path("dashboard/throughput/", views_dashboard.dashboard_throughput, name="dash_throughput"),
    path("dashboard/recent/", views_dashboard.dashboard_recent, name="dash_recent"),
    path("dashboard/failures/", views_dashboard.dashboard_failures, name="dash_failures"),

    # Legacy diagnostics URL — preserved as a redirect for bookmarks.
    path(
        "diagnostics/",
        RedirectView.as_view(pattern_name="analysis:dashboard", permanent=False),
        name="diagnostics",
    ),
]
