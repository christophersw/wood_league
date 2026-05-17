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

    --engine {all,lc0,stockfish} scopes the wipe+requeue to one engine.
    'lc0' is the #141 remediation: it corrects the garbage 20-node lc0
    data without touching the correct Stockfish jobs/results.

Changelog:
    2026-05-17: Initial creation (issue #133 — sea-trial DB reset).
    2026-05-17: Add --engine scoping for lc0-only remediation (#141).
"""
from __future__ import annotations

import json

from django.conf import settings
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


def _wipe_analysis(engines: tuple[str, ...]) -> dict[str, int]:
    """Delete analysis-result and job rows for the selected engines.

    lc0-only remediation (#141) must NOT touch Stockfish data: its
    jobs/results were correct (depth=20 is valid for SF). Children are
    deleted before parents so the operation is correct regardless of
    each FK's on_delete configuration. Only AnalysisJob rows for the
    selected engines are removed, leaving the other engine's queue and
    its partial-unique (game, engine) constraint intact.

    Parameters:
        engines: subset of ("stockfish", "lc0") to wipe.

    Returns:
        dict[str, int]: row counts deleted, keyed by model name.
    """
    deleted: dict[str, int] = {}
    if "lc0" in engines:
        deleted["Lc0MoveAnalysis"] = Lc0MoveAnalysis.objects.all().delete()[0]
        deleted["Lc0GameAnalysis"] = Lc0GameAnalysis.objects.all().delete()[0]
    if "stockfish" in engines:
        deleted["MoveAnalysis"] = MoveAnalysis.objects.all().delete()[0]
        deleted["GameAnalysis"] = GameAnalysis.objects.all().delete()[0]
    deleted["AnalysisJob"] = (
        AnalysisJob.objects.filter(engine__in=engines).delete()[0]
    )
    return deleted


def _requeue(games, engines: tuple[str, ...]) -> int:
    """Create one pending AnalysisJob per game for the selected engines.

    Parameters:
        games (Iterable[Game]): games to enqueue.
        engines: subset of ("stockfish", "lc0") to create jobs for.

    Returns:
        int: number of AnalysisJob rows created.
    """
    jobs: list[AnalysisJob] = []
    for game in games.iterator(chunk_size=_BULK_BATCH_SIZE):
        for engine in engines:
            # Pin the lc0 node budget explicitly. Leaving it NULL is what
            # let bulk-requeued lc0 jobs run at ~20 nodes (#141): the
            # worker fell back to the Stockfish depth (20). Stockfish
            # ignores nodes (it uses depth), so leave it NULL there.
            nodes = settings.LC0_NODES if engine == "lc0" else None
            jobs.append(
                AnalysisJob(
                    game=game,
                    engine=engine,
                    status=AnalysisJob.STATUS_PENDING,
                    priority=AnalysisJob.PRIORITY_NORMAL,
                    nodes=nodes,
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
        parser.add_argument(
            "--engine",
            choices=["all", "stockfish", "lc0"],
            default="all",
            help=(
                "Which engine to wipe + requeue. 'lc0' is the #141 "
                "remediation: corrects the garbage-node lc0 data and "
                "leaves the correct Stockfish jobs/results untouched. "
                "Default: all."
            ),
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
        engine_opt: str = options["engine"]
        engines: tuple[str, ...] = (
            _ENGINES if engine_opt == "all" else (engine_opt,)
        )

        if dry_run == do_it:  # neither, or contradictory both
            raise CommandError(
                "Refusing to run without an explicit mode. Pass --dry-run "
                "to preview, or --yes to perform the destructive "
                "wipe + requeue."
            )

        started_at = timezone.now()
        games = _analyzable_games(include_pgnless=include_pgnless)
        game_count = games.count()
        jobs_planned = game_count * len(engines)

        if dry_run:
            existing: dict[str, int] = {
                "AnalysisJob(%s)"
                % ",".join(engines): AnalysisJob.objects.filter(
                    engine__in=engines
                ).count(),
            }
            if "lc0" in engines:
                existing["Lc0GameAnalysis"] = Lc0GameAnalysis.objects.count()
                existing["Lc0MoveAnalysis"] = Lc0MoveAnalysis.objects.count()
            if "stockfish" in engines:
                existing["GameAnalysis"] = GameAnalysis.objects.count()
                existing["MoveAnalysis"] = MoveAnalysis.objects.count()
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN [engine={engine_opt}]: would delete "
                    f"{existing} and create {jobs_planned} pending jobs "
                    f"for {game_count} games "
                    f"(include_pgnless={include_pgnless})."
                )
            )
            return

        with transaction.atomic():
            deleted = _wipe_analysis(engines)
            jobs_created = _requeue(games, engines)

        self.stdout.write(
            self.style.SUCCESS(
                f"Requeue complete [engine={engine_opt}]: deleted "
                f"{deleted}, created {jobs_created} pending jobs for "
                f"{game_count} games."
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
                    "engine": engine_opt,
                }
            ),
        )
