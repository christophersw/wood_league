"""
Title: test_requeue_all_analysis.py — requeue_all_analysis command tests

Description:
    Verifies the #133 sea-trial reset command: it refuses to run without
    an explicit mode, --dry-run mutates nothing, and --yes wipes every
    analysis-result + job row (including MoveAnalysis children) and
    creates exactly one pending stockfish + one pending lc0 job per
    analyzable game, skipping pgn-less games unless --include-pgnless.

Changelog:
    2026-05-17: Initial creation (issue #133).
"""
import uuid

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from analysis.models import (
    AnalysisJob,
    GameAnalysis,
    Lc0GameAnalysis,
    MoveAnalysis,
)
from games.models import Game
from ingest.models import SystemEvent


def _make_game(pgn: str = "*") -> Game:
    """Create a minimal saved Game.

    Parameters:
        pgn (str): the game's PGN; "" marks it pgn-less/unanalyzable.

    Returns:
        Game: the saved instance.
    """
    return Game.objects.create(
        id=f"rq-{uuid.uuid4().hex[:10]}",
        played_at=timezone.now(),
        time_control="600",
        pgn=pgn,
    )


class RequeueAllAnalysisTests(TestCase):
    """Behavioural tests for the requeue_all_analysis command."""

    def test_requires_explicit_mode(self):
        """Running with neither --dry-run nor --yes raises CommandError."""
        with self.assertRaises(CommandError):
            call_command("requeue_all_analysis")

    def test_dry_run_mutates_nothing(self):
        """--dry-run deletes no results and creates no jobs."""
        game = _make_game()
        GameAnalysis.objects.create(game=game)
        AnalysisJob.objects.create(
            game=game, engine="stockfish", status="completed"
        )

        call_command("requeue_all_analysis", "--dry-run")

        self.assertEqual(GameAnalysis.objects.count(), 1)
        self.assertEqual(AnalysisJob.objects.count(), 1)
        self.assertFalse(
            SystemEvent.objects.filter(
                event_type="requeue_all_analysis"
            ).exists()
        )

    def test_yes_wipes_results_and_requeues_both_engines(self):
        """--yes clears all results (incl. move children) and creates one
        pending stockfish + one pending lc0 job per analyzable game."""
        g1 = _make_game()
        g2 = _make_game()
        ga = GameAnalysis.objects.create(game=g1)
        MoveAnalysis.objects.create(
            analysis=ga, ply=1, san="e4", fen="x", cp_eval=0.1
        )
        Lc0GameAnalysis.objects.create(game=g1)
        AnalysisJob.objects.create(
            game=g1, engine="stockfish", status="completed"
        )

        call_command("requeue_all_analysis", "--yes")

        self.assertEqual(GameAnalysis.objects.count(), 0)
        self.assertEqual(MoveAnalysis.objects.count(), 0)
        self.assertEqual(Lc0GameAnalysis.objects.count(), 0)

        jobs = AnalysisJob.objects.all()
        self.assertEqual(jobs.count(), 4)  # 2 games x 2 engines
        self.assertTrue(
            all(j.status == AnalysisJob.STATUS_PENDING for j in jobs)
        )
        for game in (g1, g2):
            engines = set(
                AnalysisJob.objects.filter(game=game).values_list(
                    "engine", flat=True
                )
            )
            self.assertEqual(engines, {"stockfish", "lc0"})

        self.assertTrue(
            SystemEvent.objects.filter(
                event_type="requeue_all_analysis", status="completed"
            ).exists()
        )

    def test_pgnless_games_skipped_by_default(self):
        """A pgn-less game is not requeued unless --include-pgnless."""
        _make_game(pgn="")

        call_command("requeue_all_analysis", "--yes")
        self.assertEqual(AnalysisJob.objects.count(), 0)

        call_command("requeue_all_analysis", "--yes", "--include-pgnless")
        self.assertEqual(AnalysisJob.objects.count(), 2)
