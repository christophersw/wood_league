"""
Title: urls.py — URL routing for the ingest module
Description:
    Defines URL patterns for the ingest app. Currently empty with no endpoints
    defined.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import URLPattern, URLResolver

app_name = "ingest"

urlpatterns: list[URLPattern | URLResolver] = []
