"""
Title: apps.py — Analysis app configuration
Description:
    Django AppConfig for the analysis application. Registers the analysis app
    with the Django project and provides app metadata. Initialises the RunPod
    SDK API key at startup via ready() so that settings.py stays importable
    without side effects.

Changelog:
    2026-05-08: Added file header to meet documentation standards.
    2026-05-10: A4 — set runpod.api_key in ready() from Django settings.
    2026-05-14: Issue #101 Phase A — docstring updated; the legacy push-
        dispatch flow has been removed but runpod.api_key is still needed
        by the RunPod health probe in services_queries.runpod_health().
"""
from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    """Configuration for the analysis Django app."""

    name = "analysis"

    def ready(self) -> None:
        """Initialise third-party SDK keys after Django's app registry is loaded.

        Sets runpod.api_key from Django settings so that the runpod module is
        authenticated before any view or task calls into the RunPod SDK
        (currently the health probe in services_queries.runpod_health()).
        Only sets the key when RUNPOD_API_KEY is non-empty to avoid overwriting
        a key set by test fixtures.

        Returns:
            None
        """
        from django.conf import settings

        api_key = getattr(settings, "RUNPOD_API_KEY", "")
        if api_key:
            import runpod

            runpod.api_key = api_key
