"""
Title: 0003_cache_table.py — Provision the django_cache table
Description:
    Creates the DatabaseCache backing table used by django-ratelimit so that
    per-IP rate limits aggregate across gunicorn workers instead of being
    isolated to each worker's process memory.
Changelog:
    2026-05-28: Initial (#218).
"""
from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Run `createcachetable` to provision django_cache."""
    call_command("createcachetable", "django_cache", verbosity=0)


def drop_cache_table(apps, schema_editor):
    """Drop the django_cache table on reverse migration."""
    schema_editor.execute("DROP TABLE IF EXISTS django_cache")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_loginlink"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]
