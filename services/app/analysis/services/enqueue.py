"""
Title: enqueue.py — Dedup-safe AnalysisJob creation
Description: Single source of truth for deciding whether a Game needs a new
    AnalysisJob. Replaces the dispatcher-side _enqueue_job_if_needed logic and
    centralizes dedup so issue #12 (dispatch_mode-blind dedup) cannot recur.
    Filters only by engine + game + status — never by dispatch_mode, which is
    being removed in Phase F.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
"""
from __future__ import annotations

from django.db import transaction

from analysis.models import AnalysisJob
from games.models import Game

# Statuses that indicate a job is actively being processed or waiting to run.
# A job in any of these states blocks creation of a duplicate for the same
# game+engine pair.
_ACTIVE_STATUSES = (
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
)


def enqueue_analysis_job(
    *,
    game: Game,
    engine: str,
    depth: int = 20,
    priority: int = 10,
) -> AnalysisJob | None:
    """Create a pending AnalysisJob for game+engine if dedup permits.

    Dedup rules (checked in order):
    1. Any active job (pending, running, or submitted) for game+engine → skip.
    2. A completed job at depth >= requested depth for game+engine → skip.
    3. Otherwise → create and return a new pending AnalysisJob.

    dispatch_mode is intentionally excluded from all filters — it is being
    removed in Phase F and must not affect dedup decisions.

    Args:
        game: The Game instance to analyze.
        engine: Engine name, e.g. 'stockfish' or 'lc0'.
        depth: Stockfish depth or Lc0 node budget threshold. Used to decide
            whether a completed job already satisfies the requested depth.
        priority: Job priority; higher values run first.

    Returns:
        The newly created AnalysisJob with STATUS_PENDING, or None if an
        active or sufficiently-deep completed job already exists.

    Note: This function is NOT race-safe on its own — concurrent calls for the
        same (game, engine) pair could pass the dedup check and insert duplicates.
        Callers must serialize (e.g. the sync_games command holds a Postgres
        advisory lock around its sweep). Adding a partial unique index on
        (game, engine) WHERE status IN ('pending','running','submitted') would
        make this safe without external coordination — tracked as future work.
    """
    with transaction.atomic():
        if AnalysisJob.objects.filter(
            game=game,
            engine=engine,
            status__in=_ACTIVE_STATUSES,
        ).exists():
            return None

        if AnalysisJob.objects.filter(
            game=game,
            engine=engine,
            status=AnalysisJob.STATUS_COMPLETED,
            depth__gte=depth,
        ).exists():
            return None

        return AnalysisJob.objects.create(
            game=game,
            engine=engine,
            depth=depth,
            priority=priority,
            status=AnalysisJob.STATUS_PENDING,
        )
