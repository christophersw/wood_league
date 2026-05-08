"""
Title: urls.py — Main URL routes for openings app
Description:
    Primary URL routing for the openings application, defining the opening
    detail page endpoint and app namespacing.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "openings"

urlpatterns = [
    path("<int:opening_id>/", views.detail, name="detail"),
]
