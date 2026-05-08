"""
Title: partial_urls.py — Analysis HTMX partial URL patterns
Description:
    URL routing for HTMX partial views in the analysis module. Provides
    endpoints for partial content updates in the analysis queue interface.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import views

urlpatterns = [
    path("analysis/queue/", views.queue_partial, name="analysis-queue-partial"),
]
