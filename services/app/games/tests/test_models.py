"""
Title: test_models.py — Tests for Game time-fields and GameMoveTime model.
Description:
    Confirms the new Game columns persist and that GameMoveTime cascades on
    Game deletion + enforces the (game, ply) unique constraint.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from datetime import datetime, timezone

from django.db import IntegrityError
from django.test import TestCase

from games.models import Game, GameMoveTime


class GameTimeFieldsTests(TestCase):
    def test_game_persists_time_columns(self):
        g = Game.objects.create(
            id="g-1",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            time_control="180+0",
            started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_class="blitz",
            time_control_base_s=180,
            time_control_increment_s=0,
        )
        g.refresh_from_db()
        assert g.started_at_utc.year == 2026
        assert g.time_class == "blitz"
        assert g.time_control_base_s == 180
        assert g.time_control_increment_s == 0


class GameMoveTimeTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(
            id="g-2",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            time_control="600+5",
            started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_class="rapid",
            time_control_base_s=600,
            time_control_increment_s=5,
        )

    def test_bulk_create_and_fetch(self):
        GameMoveTime.objects.bulk_create([
            GameMoveTime(game=self.game, ply=1, time_spent_ms=2_000, clock_after_ms=603_000),
            GameMoveTime(game=self.game, ply=2, time_spent_ms=5_000, clock_after_ms=600_000),
        ])
        rows = list(self.game.move_times.order_by("ply"))
        assert len(rows) == 2
        assert rows[0].time_spent_ms == 2_000
        assert rows[1].clock_after_ms == 600_000

    def test_unique_constraint_per_ply(self):
        GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=100, clock_after_ms=None)
        with self.assertRaises(IntegrityError):
            GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=200, clock_after_ms=None)

    def test_cascade_on_game_delete(self):
        GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=100, clock_after_ms=None)
        self.game.delete()
        assert GameMoveTime.objects.count() == 0
