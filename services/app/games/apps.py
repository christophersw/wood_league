"""
Title: apps.py — Games app configuration
Description:
    Django AppConfig class for the games application. Defines the app name
    and handles initialization of the games module.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class GamesConfig(AppConfig):
    """Configuration class for the games Django app."""

    name = 'games'
