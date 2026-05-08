"""
Title: apps.py — Dashboard app configuration
Description:
    Django AppConfig class for the dashboard application. Defines the app name
    and handles initialization of the dashboard module.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """Configuration class for the dashboard app."""

    name = 'dashboard'
