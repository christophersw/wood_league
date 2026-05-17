"""
Title: test_delete_test_games.py — delete_test_games command tests

Description:
    Verifies the #9 cleanup: the command refuses to run without an
    explicit mode, --dry-run mutates nothing, and --yes deletes only
    Game rows whose id starts with "test-" (cascading to children),
    leaving real games and their data untouched.

Changelog:
    2026-05-17: Initial creation (issue #9).
"""
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from analysis.models import AnalysisJob
from games.models import Game
from ingest.models import SystemEvent


def _game(game_id: str) -> Game:
    """Create a saved Game with the given id and one analysis job.

    Parameters:
        game_id (str): the Game primary key to use.

    Returns:
        Game: the saved instance (with a cascaded AnalysisJob child).
    """
    g = Game.objects.create(
        id=game_id,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )
    AnalysisJob.objects.create(game=g, engine="lc0", status="pending")
    return g


class DeleteTestGamesTests(TestCase):
    """Behavioural tests for the delete_test_games command."""

    def test_requires_explicit_mode(self):
        """Running with neither --dry-run nor --yes raises CommandError."""
        with self.assertRaises(CommandError):
            call_command("delete_test_games")

    def test_dry_run_mutates_nothing(self):
        """--dry-run deletes no games and writes no SystemEvent."""
        _game(f"test-A4-{uuid.uuid4().hex[:8]}")
        _game("real-12345")

        call_command("delete_test_games", "--dry-run")

        self.assertEqual(Game.objects.count(), 2)
        self.assertEqual(AnalysisJob.objects.count(), 2)
        self.assertFalse(
            SystemEvent.objects.filter(event_type="delete_test_games").exists()
        )

    def test_yes_deletes_only_test_games_and_cascades(self):
        """--yes removes test- games + children; real games survive."""
        _game(f"test-A4-{uuid.uuid4().hex[:8]}")
        _game(f"test-A3-{uuid.uuid4().hex[:8]}")
        _game("real-12345")

        call_command("delete_test_games", "--yes")

        remaining = list(Game.objects.values_list("id", flat=True))
        self.assertEqual(remaining, ["real-12345"])
        # The test games' AnalysisJob children cascaded away; the real
        # game's job remains.
        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertEqual(
            AnalysisJob.objects.first().game_id, "real-12345"
        )
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type="delete_test_games", status="completed"
            ).exists()
        )
