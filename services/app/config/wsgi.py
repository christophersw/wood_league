"""
Title: config/wsgi.py — WSGI application entry point for synchronous web servers
Description:
    WSGI configuration for the Wood League Django application. Exposes the WSGI callable
    as a module-level variable named 'application' for use with synchronous web servers
    like Gunicorn and uWSGI in production deployments.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
