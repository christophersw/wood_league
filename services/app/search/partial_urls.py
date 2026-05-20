"""
Title: partial_urls.py — HTMX partial endpoint URLs for search
Description:
    URL routing for HTMX partial endpoints in the search app, including
    AI-powered search, keyword search, and board preview endpoints.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

urlpatterns = [
    path("search/ai/", views.ai_search_partial, name="search_ai_partial"),
    path("search/keyword/", views.keyword_search_partial, name="search_keyword_partial"),
    path("search/board/<str:game_id>/", views.board_preview_partial, name="search_board_partial"),
    path("search/modal/<str:game_id>/", views.game_modal_partial, name="search_game_modal_partial"),
]
