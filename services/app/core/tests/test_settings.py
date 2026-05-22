"""
Title: test_settings.py — Auto-enqueue env setting wiring
Description: Verify AUTO_ENQUEUE_STOCKFISH / AUTO_ENQUEUE_LC0 exist on Django
    settings, are booleans, and default to False when their env vars are unset.
Changelog:
    2026-05-22: Initial — issue #201 (env-only auto-enqueue toggles).
"""
from django.conf import settings


def test_auto_enqueue_settings_exist_and_are_bool():
    """Both toggles must be present and boolean-typed."""
    assert isinstance(settings.AUTO_ENQUEUE_STOCKFISH, bool)
    assert isinstance(settings.AUTO_ENQUEUE_LC0, bool)


def test_auto_enqueue_settings_default_false():
    """With the env vars unset (test environment), both default to False."""
    assert settings.AUTO_ENQUEUE_STOCKFISH is False
    assert settings.AUTO_ENQUEUE_LC0 is False
