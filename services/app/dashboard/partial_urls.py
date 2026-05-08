"""
Title: partial_urls.py — HTMX partial endpoint URLs for dashboard
Description:
    URL routing for HTMX partial endpoints in the dashboard app, including
    accuracy charts, ELO trends, Sankey diagrams, and game tables.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/accuracy/", views.accuracy_chart_partial, name="dashboard_accuracy"),
    path("dashboard/elo/", views.elo_chart_partial, name="dashboard_elo"),
    path("dashboard/sankey/", views.sankey_partial, name="dashboard_sankey"),
    path("dashboard/opening-stats/", views.opening_node_stats_partial, name="dashboard_opening_stats"),
    path("dashboard/best-recent/", views.best_recent_partial, name="dashboard_best_recent"),
    path("dashboard/best-alltime/", views.best_alltime_partial, name="dashboard_best_alltime"),
]
