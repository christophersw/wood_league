"""
Title: conftest.py — Pytest root configuration for Django app
Description:
    Configures Django settings before test collection to prevent
    AppRegistryNotReady errors when model imports occur during collection.
    This file is discovered automatically by pytest at session startup,
    before any test modules are imported.

Changelog:
    2026-05-08: Created to fix AppRegistryNotReady in api/tests/
"""

import os

import django


def pytest_configure(config):
    """Configure Django before pytest collects any test modules.

    Parameters:
        config: The pytest Config object (provided by the pytest hook system).

    Returns:
        None

    Side effects:
        Sets DJANGO_SETTINGS_MODULE env var and calls django.setup(), which
        initialises the app registry so model imports during collection succeed.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()
