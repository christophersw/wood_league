"""
Title: partial_urls.py — HTMX partial URL patterns for the games app
Description:
    URL patterns for HTMX-loaded board and queue partials. Registered under
    /_partials/ in the main URL config.

Changelog:
    2026-05-04 (#16): Added board_partial and queue_analysis endpoints
"""

from django.urls import path

from . import views

urlpatterns = [
    path("games/<slug:slug>/board/", views.board_partial, name="games_board_partial"),
    path("games/<slug:slug>/engine-line/", views.engine_line_partial, name="games_engine_line_partial"),
    path("games/<slug:slug>/queue/", views.queue_analysis, name="games_queue_analysis"),
]
