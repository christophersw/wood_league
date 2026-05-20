"""
Title: test_backfill_opening_ids.py
Description: backfill_opening_ids fills Game.opening_id for null rows.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from datetime import datetime, timezone

import pytest
from django.core.management import call_command

from games.models import Game
from openings.models import OpeningBook


@pytest.mark.django_db
def test_backfill_sets_opening_id(monkeypatch):
    """Verify backfill_opening_ids sets opening_id when resolver returns a match."""
    # Create a valid OpeningBook entry so the FK target exists.
    OpeningBook.objects.create(id=99, name="Test Opening")

    g = Game.objects.create(
        id="t1",
        slug="t-1",
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="180+0",
        pgn="[Event \"t\"]\n\n1. e4 e5 *",
    )
    monkeypatch.setattr(
        "games.management.commands.backfill_opening_ids.resolve_opening_id",
        lambda _pgn: 99,
    )
    call_command("backfill_opening_ids")
    g.refresh_from_db()
    assert g.opening_id == 99


@pytest.mark.django_db
def test_backfill_dry_run_does_not_write(monkeypatch):
    """Verify --dry-run flag prevents database writes."""
    # Create a valid OpeningBook entry (not used in dry-run but needed for return value).
    OpeningBook.objects.create(id=1, name="Test Opening 2")

    g = Game.objects.create(
        id="t2",
        slug="t-2",
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="180+0",
        pgn="x",
    )
    monkeypatch.setattr(
        "games.management.commands.backfill_opening_ids.resolve_opening_id",
        lambda _pgn: 1,
    )
    call_command("backfill_opening_ids", "--dry-run")
    g.refresh_from_db()
    assert g.opening_id is None
