"""
Title: test_backfill_move_times.py — Tests for the backfill management command.
Description:
    Verifies the command writes GameMoveTime rows for games with valid PGN,
    is idempotent on re-run, honours --limit, and reports counts in --dry-run.

Changelog:
    2026-05-11: Initial creation (issue #24).
    2026-05-11: Add test for SystemEvent logging (issue #24).
"""
import json as _json
from datetime import datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from games.models import Game, GameMoveTime
from ingest.models import SystemEvent


_PGN_LIVE = (
    '[Event "Live Chess"]\n[TimeControl "180"]\n\n'
    '1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:02:58]} 1-0\n'
)
_PGN_DAILY = (
    '[Event "Lets Play!"]\n[TimeControl "1/604800"]\n\n'
    '1. e4 {[%clk 0:00:00.5]} 1... c6 {[%clk 0:30:05.2]} 1-0\n'
)


def _make_game(game_id, *, time_class, time_control, base_s, inc_s, pgn):
    """
    Create a Game fixture for testing.

    Parameters:
        game_id (str): Unique identifier for the game.
        time_class (str): Chess.com time class (e.g. 'blitz', 'daily').
        time_control (str): Raw time control string from Chess.com.
        base_s (int): Base clock time in seconds.
        inc_s (int | None): Increment in seconds, or None.
        pgn (str): PGN string with %clk annotations.

    Returns:
        Game: The created Game instance.
    """
    return Game.objects.create(
        id=game_id,
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control=time_control,
        time_class=time_class,
        time_control_base_s=base_s,
        time_control_increment_s=inc_s,
        started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        pgn=pgn,
    )


class BackfillMoveTimesTests(TestCase):
    def test_writes_rows_for_live_and_daily(self):
        _make_game("bf-1", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        _make_game("bf-2", time_class="daily", time_control="1/604800", base_s=604800, inc_s=None, pgn=_PGN_DAILY)

        out = StringIO()
        call_command("backfill_move_times", stdout=out)

        assert GameMoveTime.objects.filter(game_id="bf-1").count() == 2
        assert GameMoveTime.objects.filter(game_id="bf-2").count() == 2

    def test_idempotent_on_rerun(self):
        _make_game("bf-3", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        call_command("backfill_move_times", stdout=StringIO())
        call_command("backfill_move_times", stdout=StringIO())  # no double-write
        assert GameMoveTime.objects.filter(game_id="bf-3").count() == 2

    def test_dry_run_writes_nothing(self):
        _make_game("bf-4", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        out = StringIO()
        call_command("backfill_move_times", "--dry-run", stdout=out)
        assert GameMoveTime.objects.filter(game_id="bf-4").count() == 0
        assert "would write" in out.getvalue().lower()

    def test_limit_caps_processing(self):
        _make_game("bf-5", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        _make_game("bf-6", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        call_command("backfill_move_times", "--limit", "1", stdout=StringIO())
        total = GameMoveTime.objects.filter(game_id__in=["bf-5", "bf-6"]).count()
        assert total == 2  # exactly one game processed (2 plies each)

    def test_writes_system_event_on_completion(self):
        _make_game("bf-7", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        call_command("backfill_move_times", stdout=StringIO())
        events = SystemEvent.objects.filter(event_type="backfill_move_times")
        assert events.count() == 1
        event = events.first()
        assert event.status == "completed"
        assert event.completed_at is not None
        details = _json.loads(event.details)
        assert details["games_seen"] >= 1
        assert details["rows_written"] >= 2
