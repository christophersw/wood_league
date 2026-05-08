"""
Title: partial_urls.py — HTMX partial endpoint URLs for openings
Description:
    URL routing for HTMX partial endpoints in the openings app, serving
    opening statistics charts and game tables filtered by scope parameters.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

urlpatterns = [
    path("openings/<int:opening_id>/stats/", views.stats_partial, name="openings-stats-partial"),
]
