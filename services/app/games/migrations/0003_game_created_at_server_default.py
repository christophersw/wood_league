"""
Title: 0003_game_created_at_server_default
Description:
    Adds a Postgres-side DEFAULT NOW() to games.created_at so non-Django
    inserters (the SQLAlchemy ingest path in app/ingest/sync_service.py)
    populate the column automatically. Also backfills existing NULL rows
    from played_at as a sensible historical proxy.

    Why: Django's `auto_now_add=True` only fires on Django ORM .save() —
    the SQLAlchemy fork inserts directly, so created_at stayed NULL on
    fresh ingests, breaking sync_games' "newly inserted" detection
    (created_at__gte=started_at).

Changelog:
    2026-05-11: Initial — backfills NULLs from played_at + adds server default.
"""

from django.db import migrations


class Migration(migrations.Migration):
    """Add server-side default and backfill NULL created_at rows."""

    dependencies = [
        ("games", "0002_add_game_created_at"),
    ]

    operations = [
        migrations.RunSQL(
            sql="UPDATE games SET created_at = played_at WHERE created_at IS NULL;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="ALTER TABLE games ALTER COLUMN created_at SET DEFAULT NOW();",
            reverse_sql="ALTER TABLE games ALTER COLUMN created_at DROP DEFAULT;",
        ),
    ]
