"""
Title: apps.py — Django app configuration for the ingest module
Description:
    Configuration class for the ingest application. Registers the ingest app
    with Django and sets its module name.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class IngestConfig(AppConfig):
    """Configuration class for the ingest app."""

    name = 'ingest'
