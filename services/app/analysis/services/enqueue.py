"""
Title: enqueue.py — Dedup-safe AnalysisJob creation
Description: Single source of truth for deciding whether a Game needs a new
    AnalysisJob. The active-job dedup invariant is enforced by a partial
    unique index on (game, engine) WHERE status IN ('pending','running',
    'submitted'), so this function is safe under concurrent callers without
    external coordination. The pre-check .exists() queries remain as a fast
    path in the uncontended case.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
    2026-05-11: Race-safe via partial unique constraint (issue #15).
"""
from __future__ import annotations

from django.db import IntegrityError

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
    3. Otherwise → attempt to create. If the partial unique index rejects the
       insert (a concurrent caller raced in between the pre-check and the
       create), treat as dedup-skip and return None.

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
        active or sufficiently-deep completed job already exists, or if a
        concurrent caller won the race for the active slot.
    """
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

    try:
        return AnalysisJob.objects.create(
            game=game,
            engine=engine,
            depth=depth,
            priority=priority,
            status=AnalysisJob.STATUS_PENDING,
        )
    except IntegrityError:
        # Lost the race: another caller inserted an active row for this
        # (game, engine) between our pre-check and our INSERT. The partial
        # unique constraint rejected our row, which is semantically the
        # same as the dedup-skip path above.
        return None
