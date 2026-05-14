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
        dispatch flow has been removed.
    2026-05-14 (#106): Drop references to the removed runpod_health probe.
        runpod.api_key initialisation is retained for any future SDK use
        (e.g. start_pod in runpod_start_view).
"""
from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    """Configuration for the analysis Django app."""

    name = "analysis"

    def ready(self) -> None:
        """Initialise third-party SDK keys after Django's app registry is loaded.

        Sets runpod.api_key from Django settings so that the runpod module is
        authenticated before any view or task calls into the RunPod SDK
        (e.g. ``start_pod`` invoked from ``runpod_start_view``). Only sets the
        key when RUNPOD_API_KEY is non-empty to avoid overwriting a key set by
        test fixtures.

        Returns:
            None
        """
        from django.conf import settings

        api_key = getattr(settings, "RUNPOD_API_KEY", "")
        if api_key:
            import runpod

            runpod.api_key = api_key
