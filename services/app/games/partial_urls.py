"""
Title: partial_urls.py — HTMX partial URL patterns for the games app
Description:
    URL patterns for HTMX-loaded board and queue partials. Registered under
    /_partials/ in the main URL config.

Changelog:
    2026-05-04 (#16): Added board_partial and queue_analysis endpoints
    2026-05-27 (#216): Task 8 — remove games_chart_winpct_partial route.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("games/<slug:slug>/board/", views.board_partial, name="games_board_partial"),
    path("games/<slug:slug>/engine-line/", views.engine_line_partial, name="games_engine_line_partial"),
    path("games/<slug:slug>/queue/", views.queue_analysis, name="games_queue_analysis"),
    path("games/<slug:slug>/cards/sf/", views.card_sf_partial, name="games_card_sf_partial"),
    path("games/<slug:slug>/cards/lc0/", views.card_lc0_partial, name="games_card_lc0_partial"),
    path("games/<slug:slug>/chips/", views.chips_partial, name="games_chips_partial"),
    path("games/<slug:slug>/charts/sf-cp/", views.chart_sf_cp_partial, name="games_chart_sf_cp_partial"),
    path("games/<slug:slug>/charts/lc0-wdl/", views.chart_lc0_wdl_partial, name="games_chart_lc0_wdl_partial"),
    path("games/<slug:slug>/pgn/", views.pgn_partial, name="games_pgn_partial"),
]
