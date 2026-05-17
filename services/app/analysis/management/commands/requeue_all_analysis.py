"""
Title: requeue_all_analysis.py — Wipe all engine analysis and requeue every game

Description:
    Destructive maintenance command for the #133 sea-trial reset. In a
    single transaction it deletes ALL existing engine-analysis results
    (GameAnalysis, MoveAnalysis, Lc0GameAnalysis, Lc0MoveAnalysis) and ALL
    AnalysisJob rows, then creates one fresh `pending` AnalysisJob per
    analyzable game for BOTH engines (stockfish + lc0) so the worker pull
    API serves them again.

    The result-table wipe is mandatory, not cosmetic: analysis.services.
    jobs.claim_jobs skips a job when a GameAnalysis / Lc0GameAnalysis row
    already exists for that game, so stale results would silently suppress
    the requeue.

    "Analyzable" = Game.pgn non-empty (a game with no PGN only yields a
    failed job). Pass --include-pgnless to queue every Game regardless.

    Safety: requires an explicit mode. --dry-run reports counts and writes
    nothing. --yes performs the destructive wipe+requeue. Running with
    neither aborts with instructions (no accidental prod wipe).

Changelog:
    2026-05-17: Initial creation (issue #133 — sea-trial DB reset).
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from analysis.models import (
    AnalysisJob,
    GameAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    MoveAnalysis,
)
from games.models import Game
from ingest.models import SystemEvent

_BULK_BATCH_SIZE = 1000
_EVENT_TYPE = "requeue_all_analysis"
_ENGINES = ("stockfish", "lc0")


def _analyzable_games(*, include_pgnless: bool):
    """Return the Game queryset to requeue.

    Parameters:
        include_pgnless (bool): When False (default) only games with a
            non-empty pgn are returned, since a pgn-less game only yields
            a failed job. When True, every Game is returned.

    Returns:
        QuerySet[Game]: games to create pending jobs for, ordered by id.
    """
    qs = Game.objects.all()
    if not include_pgnless:
        qs = qs.filter(pgn__gt="")
    return qs.order_by("id")


def _wipe_all_analysis() -> dict[str, int]:
    """Delete every analysis-result and job row.

    Children are deleted before parents so the operation is correct
    regardless of each FK's on_delete configuration.

    Returns:
        dict[str, int]: row counts deleted, keyed by model name.
    """
    deleted: dict[str, int] = {}
    deleted["Lc0MoveAnalysis"] = Lc0MoveAnalysis.objects.all().delete()[0]
    deleted["Lc0GameAnalysis"] = Lc0GameAnalysis.objects.all().delete()[0]
    deleted["MoveAnalysis"] = MoveAnalysis.objects.all().delete()[0]
    deleted["GameAnalysis"] = GameAnalysis.objects.all().delete()[0]
    deleted["AnalysisJob"] = AnalysisJob.objects.all().delete()[0]
    return deleted


def _requeue(games) -> int:
    """Create one pending AnalysisJob per game per engine.

    Parameters:
        games (Iterable[Game]): games to enqueue.

    Returns:
        int: number of AnalysisJob rows created.
    """
    jobs: list[AnalysisJob] = []
    for game in games.iterator(chunk_size=_BULK_BATCH_SIZE):
        for engine in _ENGINES:
            jobs.append(
                AnalysisJob(
                    game=game,
                    engine=engine,
                    status=AnalysisJob.STATUS_PENDING,
                    priority=AnalysisJob.PRIORITY_NORMAL,
                )
            )
    AnalysisJob.objects.bulk_create(jobs, batch_size=_BULK_BATCH_SIZE)
    return len(jobs)


class Command(BaseCommand):
    """Wipe all engine analysis and requeue every analyzable game (#133)."""

    help = (
        "DESTRUCTIVE: delete all GameAnalysis/MoveAnalysis/Lc0* and "
        "AnalysisJob rows, then create fresh pending jobs (stockfish+lc0) "
        "for every analyzable game. Requires --dry-run or --yes."
    )

    def add_arguments(self, parser):
        """Register CLI flags.

        Parameters:
            parser (ArgumentParser): Django's argument parser instance.
        """
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts only; delete and write nothing.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Perform the destructive wipe + requeue.",
        )
        parser.add_argument(
            "--include-pgnless",
            action="store_true",
            help="Also queue games with no PGN (default: skip them).",
        )

    def handle(self, *args, **options):
        """Wipe all analysis and requeue every analyzable game.

        Parameters:
            args: Positional arguments (unused).
            options (dict): Parsed CLI options: dry_run, yes,
                include_pgnless.

        Side effects:
            Unless --dry-run: deletes all analysis-result + AnalysisJob
            rows and bulk-creates pending jobs, inside one transaction;
            writes a SystemEvent audit row. Outputs a summary to stdout.

        Raises:
            CommandError: if neither --dry-run nor --yes is supplied.
        """
        dry_run: bool = options["dry_run"]
        do_it: bool = options["yes"]
        include_pgnless: bool = options["include_pgnless"]

        if dry_run == do_it:  # neither, or contradictory both
            raise CommandError(
                "Refusing to run without an explicit mode. Pass --dry-run "
                "to preview, or --yes to perform the destructive "
                "wipe + requeue."
            )

        started_at = timezone.now()
        games = _analyzable_games(include_pgnless=include_pgnless)
        game_count = games.count()
        jobs_planned = game_count * len(_ENGINES)

        if dry_run:
            existing = {
                "GameAnalysis": GameAnalysis.objects.count(),
                "MoveAnalysis": MoveAnalysis.objects.count(),
                "Lc0GameAnalysis": Lc0GameAnalysis.objects.count(),
                "Lc0MoveAnalysis": Lc0MoveAnalysis.objects.count(),
                "AnalysisJob": AnalysisJob.objects.count(),
            }
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: would delete {existing} and create "
                    f"{jobs_planned} pending jobs for {game_count} games "
                    f"(include_pgnless={include_pgnless})."
                )
            )
            return

        with transaction.atomic():
            deleted = _wipe_all_analysis()
            jobs_created = _requeue(games)

        self.stdout.write(
            self.style.SUCCESS(
                f"Requeue complete: deleted {deleted}, created "
                f"{jobs_created} pending jobs for {game_count} games."
            )
        )

        completed_at = timezone.now()
        SystemEvent.objects.create(
            event_type=_EVENT_TYPE,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=(completed_at - started_at).total_seconds(),
            details=json.dumps(
                {
                    "deleted": deleted,
                    "jobs_created": jobs_created,
                    "game_count": game_count,
                    "include_pgnless": include_pgnless,
                }
            ),
        )
