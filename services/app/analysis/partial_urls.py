"""
Title: partial_urls.py — Analysis HTMX partial URL patterns
Description:
    HTMX partial routes for the analysis module. The legacy
    ``analysis/queue/`` overview-cards partial was removed in #200 along
    with the queue pages; no analysis partials remain at present.

Changelog:
    2026-05-22 (#200): Remove analysis/queue/ overview_partial route.
    2026-05-10: Task C1 — repoint analysis/queue/ to overview_partial view.
"""
from django.urls import path  # noqa: F401  (kept for future partials)

urlpatterns: list = []
