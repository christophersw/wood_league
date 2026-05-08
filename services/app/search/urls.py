"""
Title: urls.py — Main URL routes for search app
Description:
    Primary URL routing for the search application, defining the main search
    index page endpoint and app namespacing.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "search"

urlpatterns = [
    path("", views.search_index, name="index"),
]
