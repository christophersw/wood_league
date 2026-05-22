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
    2026-05-15: Refuse to enqueue 0-move PGNs — workers cannot analyse
        them and were being looped through retry until MAX_JOB_RETRIES
        (issue #112).
"""
from __future__ import annotations

import io
import logging

import chess.pgn
from django.db import IntegrityError

from analysis.models import AnalysisJob
from games.models import Game

log = logging.getLogger(__name__)

# Statuses that indicate a job is actively being processed or waiting to run.
# A job in any of these states blocks creation of a duplicate for the same
# game+engine pair.
# Also imported by ingest/management/commands/sync_games.py to build the
# auto-enqueue sweep's Exists() subquery — keep this name stable.
_ACTIVE_STATUSES = (
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
)


def _pgn_has_moves(pgn_text: str) -> bool:
    """Return True when the PGN parses to at least one ply.

    Engines refuse to analyse 0-ply games (they raise ``ValueError("PGN has
    no moves …")``) and any job we create for one is wasted: it claims a
    checkout slot, fails, retries up to MAX_JOB_RETRIES times, then sits as
    a permanently-failed row. Filter these out at enqueue time.

    Args:
        pgn_text: Raw PGN as stored on ``Game.pgn``. May be empty.

    Returns:
        True if at least one move parses cleanly; False for empty input,
        headers-only PGNs, or unparseable input.
    """
    if not pgn_text or not pgn_text.strip():
        return False
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 - any parse failure is treated as no-moves
        return False
    if game is None:
        return False
    # game.mainline_moves() is an iterator; pulling one element is cheap and
    # avoids materialising the whole move list for long games.
    return next(iter(game.mainline_moves()), None) is not None


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
    if not _pgn_has_moves(game.pgn):
        log.info(
            "enqueue: skipping game %s for engine %s — PGN has no moves",
            game.pk, engine,
        )
        return None

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
