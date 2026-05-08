"""
Title: urls.py — Main URL routes for games app
Description:
    Primary URL routing for the games application, defining the game analysis
    detail page endpoint and app namespacing.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "games"

urlpatterns = [
    path("<slug:slug>/", views.game_analysis, name="analysis"),
]
