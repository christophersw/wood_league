"""
Title: urls.py — URL routing for the analysis module
Description:
    Routes for the combined /admin/analysis/ page (worker dashboard +
    scheduling), its HTMX-polled dashboard partials, the scheduling
    action endpoints, and the RunPod start hook.

Changelog:
    2026-05-22 (#200): Collapse to a single /admin/analysis/ page. Remove
        the queue pages, the legacy dashboard shell, the schedule shell
        route, and the diagnostics redirect. Repath dashboard partials
        under analysis/ (names unchanged).
    2026-05-18: Add /schedule/ routes (#155 B).
    2026-05-14 (#106): Add /dashboard/ + HTMX partial routes.
"""
from django.urls import path

from . import views, views_dashboard, views_schedule

app_name = "analysis"

urlpatterns = [
    path("runpod/start/", views.runpod_start_view, name="runpod_start"),

    # Combined analysis page (dashboard + scheduling) — #200.
    path("analysis/", views_schedule.overview, name="overview"),

    # Dashboard partials (HTMX-polled by the overview page).
    path("analysis/banner/", views_dashboard.dashboard_banner, name="dash_banner"),
    path("analysis/workers/", views_dashboard.dashboard_workers, name="dash_workers"),
    path("analysis/queues/", views_dashboard.dashboard_queues, name="dash_queues"),
    path("analysis/throughput/", views_dashboard.dashboard_throughput, name="dash_throughput"),
    path("analysis/recent/", views_dashboard.dashboard_recent, name="dash_recent"),
    path("analysis/failures/", views_dashboard.dashboard_failures, name="dash_failures"),
    path("analysis/logs/", views_dashboard.dashboard_logs, name="dash_logs"),

    # Scheduling actions (forms POST here; redirect to analysis:overview).
    path("schedule/rule/new/", views_schedule.rule_create, name="rule_create"),
    path("schedule/rule/<int:pk>/edit/", views_schedule.rule_edit, name="rule_edit"),
    path("schedule/rule/<int:pk>/delete/", views_schedule.rule_delete, name="rule_delete"),
    path("schedule/rule/<int:pk>/toggle/", views_schedule.rule_toggle, name="rule_toggle"),
    path("schedule/run-once/", views_schedule.run_once, name="run_once"),
    path("schedule/<int:pk>/rerun/", views_schedule.rerun, name="rerun"),
    path("schedule/preview/", views_schedule.schedule_preview, name="schedule_preview"),
]
