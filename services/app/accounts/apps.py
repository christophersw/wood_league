"""
Title: apps.py — Accounts app configuration
Description:
    Django AppConfig for the accounts application. Registers the accounts app
    with the Django project and provides app metadata.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Configuration class for the accounts app."""
    name = 'accounts'
