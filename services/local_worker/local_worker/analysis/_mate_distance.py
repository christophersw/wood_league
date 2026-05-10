"""
Title: _mate_distance.py — Mate-distance penalty heuristic
Description:
    Engine cp evaluations flatten all forced-mate positions to ±MATE_SCORE
    (10000), so the standard CPL formula returns 0 for both
    "mate-in-1 → mate-in-1 played" and "mate-in-1 → mate-in-10 played" —
    even though the second case is a meaningful quality drop. This module
    computes an additive CPL penalty driven by the change in mate distance
    reported by the engine before and after the move.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import chess
import chess.engine

# Penalty constants (analysis-math.md "Mate-distance heuristic")
MATE_LOST_CPL = 500       # mover had mate before, has none after — Blunder tier
MATE_PER_EXTRA_PLY = 50   # mover still has mate but took longer than necessary


def mate_distance_cpl(before_mate: int | None, after_mate: int | None) -> int:
    """Additional CPL when the mover had mate before but did not play
    the shortest forced mate.

    Args:
        before_mate: Signed mate plies from the mover's perspective before
            the move. Positive = mover delivers mate in N plies; negative
            = mover is mated in N plies; None = engine did not report a
            forced mate.
        after_mate: Same convention, evaluated after the move (still in
            the original mover's perspective).

    Returns:
        Non-negative cp penalty to add to the move's CPL. 0 if the mover
        had no forced mate before the move; ``MATE_LOST_CPL`` if the
        mover had mate but lost it; otherwise
        ``MATE_PER_EXTRA_PLY`` per ply taken beyond the optimal
        ``before_mate - 1`` plies.
    """
    if before_mate is None or before_mate <= 0:
        return 0
    if after_mate is None or after_mate <= 0:
        return MATE_LOST_CPL
    extra = max(0, after_mate - (before_mate - 1))
    return extra * MATE_PER_EXTRA_PLY


def mover_mate(score: chess.engine.PovScore, mover: chess.Color) -> int | None:
    """Return signed mate plies from the mover's perspective, or None.

    Args:
        score: PovScore returned by the engine.
        mover: Side whose perspective is wanted.

    Returns:
        Positive = mover delivers mate in N plies; negative = mover is
        being mated in N plies; None if no forced mate is detected.
    """
    return score.pov(mover).mate()
