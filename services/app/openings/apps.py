"""
Title: apps.py — Openings app configuration
Description:
    Django AppConfig class for the openings application. Defines the app name
    and handles initialization of the openings module.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class OpeningsConfig(AppConfig):
    """Configuration for the openings app."""

    name = 'openings'
