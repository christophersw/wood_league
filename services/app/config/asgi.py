"""
Title: config/asgi.py — ASGI application entry point for async web servers
Description:
    ASGI configuration for the Wood League Django application. Exposes the ASGI callable
    as a module-level variable named 'application' for use with async web servers like
    Uvicorn and Daphne in production deployments.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
