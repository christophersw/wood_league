"""
Title: partial_urls.py — Analysis HTMX partial URL patterns
Description:
    URL routing for HTMX partial views in the analysis module. Provides
    endpoints for partial content updates in the analysis queue interface.

    The ``analysis/queue/`` path now serves the overview-cards partial
    (``_overview_cards.html``) used by the /analysis/ overview page. The old
    ``_queue_partial.html`` rendering has been replaced (Task C1).

Changelog:
    2026-05-10: Task C1 — repoint analysis/queue/ to overview_partial view.
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import views

urlpatterns = [
    path("analysis/queue/", views.overview_partial, name="analysis-queue-partial"),
]
