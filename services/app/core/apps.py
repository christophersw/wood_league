"""
Title: apps.py — App config for the core app
Description: Registers the core app with Django; holds site-wide configuration models.
Changelog:
    2026-05-10: Initial — Task A1 of scrap-dispatchers plan.
"""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    """App config for site-wide configuration models."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
