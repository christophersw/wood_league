#!/usr/bin/env python
"""
Title: manage.py — Django management command entry point
Description:
    Entry point for Django administrative tasks and command-line operations. Configures
    the Django settings module and delegates to Django's core management command handler.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
