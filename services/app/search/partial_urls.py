"""HTMX partial URL routes for the search app."""

from django.urls import path
from . import views

urlpatterns = [
    path("search/ai/", views.ai_search_partial, name="search_ai_partial"),
    path("search/keyword/", views.keyword_search_partial, name="search_keyword_partial"),
    path("search/board/<str:game_id>/", views.board_preview_partial, name="search_board_partial"),
]
