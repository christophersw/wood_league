"""
Title: apps.py — Django app configuration for the API module
Description:
    Configuration class for the API application. Registers the API app with
    Django and sets its module name.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
