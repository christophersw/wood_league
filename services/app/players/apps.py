"""
Title: apps.py — Django app configuration for the players module
Description:
    Configuration class for the players application. Registers the players app
    with Django and sets its module name.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class PlayersConfig(AppConfig):
    """Configuration for the players app."""

    name = 'players'
