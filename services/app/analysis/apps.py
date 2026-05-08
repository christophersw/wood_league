"""
Title: apps.py — Analysis app configuration
Description:
    Django AppConfig for the analysis application. Registers the analysis app
    with the Django project and provides app metadata.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    """Configuration for the analysis Django app."""
    name = 'analysis'
