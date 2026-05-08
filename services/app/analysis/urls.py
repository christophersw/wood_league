"""
Title: urls.py — URL routing for analysis module views
Description:
    Defines URL patterns for game analysis dashboard views, including the status
    page that displays analysis job queue metrics and worker health information.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import views

app_name = "analysis"

urlpatterns = [
    path("analysis-status/", views.status, name="status"),
]
