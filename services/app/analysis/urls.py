"""
Title: urls.py — URL routing for analysis module views
Description:
    Defines URL patterns for game analysis dashboard views, including the queues
    summary page that displays analysis job queue metrics and worker health
    information, plus per-engine queue detail and action endpoints.

Changelog:
    2026-05-11: Task 4 — rename URL family to /admin/queues/ (plural);
        rename route 'status' → 'queues_summary'; remove old /analysis-status/ path.
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import views, views_queue

app_name = "analysis"

urlpatterns = [
    path("queues/", views.queues_summary, name="queues_summary"),
    path("queues/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queues/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    path("queues/<str:engine>/submit/", views_queue.queue_submit, name="queue_submit"),
    path("queues/<str:engine>/reorder/", views_queue.queue_reorder, name="queue_reorder"),
]
