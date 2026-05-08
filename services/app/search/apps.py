"""
Title: apps.py — Search app configuration
Description:
    Django AppConfig class for the search application. Defines the app name
    and handles initialization of the search module.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class SearchConfig(AppConfig):
    """Configuration class for the search app."""

    name = 'search'
