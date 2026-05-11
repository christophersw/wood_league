"""
Title: test_sync_games_command.py — Auto-enqueue + advisory-lock tests
Description: Verifies the management command enqueues stockfish jobs for
    newly-inserted games when the SiteSettings flag is on, and that a held
    advisory lock causes the command to exit zero without running the sync.
Changelog:
    2026-05-10: Initial — Task D1 of scrap-dispatchers plan.
"""
import uuid
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from analysis.models import AnalysisJob
from core.models import SiteSettings
from games.models import Game
from players.models import Player


def _make_player(username: str) -> Player:
    """Create a minimal Player instance.

    Args:
        username: Chess.com username for the player.

    Returns:
        Player: A saved Player instance.
    """
    return Player.objects.create(username=username, display_name=username)


class SyncGamesCommandTests(TestCase):
    """Tests for the sync_games management command advisory-lock and auto-enqueue."""

    def setUp(self):
        """Ensure SiteSettings singleton exists with defaults (sf=True, lc0=False)."""
        SiteSettings.get_solo()

    def test_auto_enqueue_creates_stockfish_jobs_when_flag_on(self):
        """sync_games should auto-enqueue stockfish jobs for newly inserted games."""
        suffix = uuid.uuid4().hex[:8]

        def fake_run(*args, **kwargs):
            """Simulate run_sync.py creating two new games."""
            Game.objects.create(
                id=f"d1-new1-{suffix}",
                played_at=timezone.now(),
                time_control="600",
                pgn="1. e4 *",
            )
            Game.objects.create(
                id=f"d1-new2-{suffix}",
                played_at=timezone.now(),
                time_control="600",
                pgn="1. d4 *",
            )
            return MagicMock(returncode=0)

        _make_player(f"alice-{suffix}")
        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            out = StringIO()
            call_command("sync_games", f"alice-{suffix}", stdout=out)

        new_sf = AnalysisJob.objects.filter(
            engine="stockfish", game__id__startswith="d1-new"
        )
        self.assertEqual(new_sf.count(), 2)

        new_lc0 = AnalysisJob.objects.filter(
            engine="lc0", game__id__startswith="d1-new"
        )
        self.assertEqual(new_lc0.count(), 0)

    def test_subprocess_runs_with_pythonpath_set(self):
        """run_sync.py imports `from app.config import ...` and needs services/app on PYTHONPATH."""
        suffix = uuid.uuid4().hex[:8]
        _make_player(f"alice-{suffix}")
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args[0] if args else kwargs.get("args")
            captured["env"] = kwargs.get("env", {})
            return MagicMock(returncode=0)

        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        env = captured["env"]
        assert "PYTHONPATH" in env, "subprocess must receive PYTHONPATH"
        # Path must end at services/app (the parent of the `app` package)
        assert env["PYTHONPATH"].endswith("/services/app"), env["PYTHONPATH"]

    def test_subprocess_passes_usernames_via_flag(self):
        """run_sync.py expects `--usernames=a,b,c`, not positional args."""
        s1 = f"alice-{uuid.uuid4().hex[:6]}"
        s2 = f"bob-{uuid.uuid4().hex[:6]}"
        _make_player(s1)
        _make_player(s2)
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args[0] if args else kwargs.get("args")
            return MagicMock(returncode=0)

        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            call_command("sync_games", stdout=StringIO())

        cmd_args = captured["args"]
        # Must contain "--usernames" with comma-joined value
        assert "--usernames" in cmd_args, cmd_args
        flag_idx = cmd_args.index("--usernames")
        value = cmd_args[flag_idx + 1]
        assert s1 in value and s2 in value, value
        assert "," in value, value
        # And no bare positional usernames trailing the script path
        # (the value after --usernames is its argument, not a positional)
        assert s1 not in cmd_args[: flag_idx + 1], cmd_args
        assert s2 not in cmd_args[: flag_idx + 1], cmd_args

    def test_held_advisory_lock_skips_sync(self):
        """If pg_try_advisory_lock returns false, the subprocess is not invoked."""
        with patch(
            "ingest.management.commands.sync_games._try_acquire_lock",
            return_value=False,
        ), patch(
            "ingest.management.commands.sync_games.subprocess.run"
        ) as mock_run:
            out = StringIO()
            call_command("sync_games", "alice", stdout=out)
        mock_run.assert_not_called()
