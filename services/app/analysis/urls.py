"""
Title: urls.py — URL routing for analysis module views
Description:
    Defines URL patterns for game analysis dashboard views, including the status
    page that displays analysis job queue metrics and worker health information.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import views, views_queue

app_name = "analysis"

urlpatterns = [
    path("analysis-status/", views.status, name="status"),
    path("queue/stockfish/", views_queue.queue_stockfish, name="queue_stockfish"),
    path("queue/lc0/", views_queue.queue_lc0, name="queue_lc0"),
    path("queue/<str:engine>/submit/", views_queue.queue_submit, name="queue_submit"),
    path("queue/<str:engine>/reorder/", views_queue.queue_reorder, name="queue_reorder"),
]
