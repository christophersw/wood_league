"""
Title: _frame.py — mover↔white frame helpers shared by lc0 + Stockfish derivation
Description:
    Issue #161 Phase C. Stockfish emits centipawn evaluations in White's frame
    (positive = White advantage); lc0 emits WDL triples in the *mover's* frame.
    Game-wide volatility windowing (see ``accuracy``) lives in White's frame
    so the same Win% sequence covers both players. These helpers are the only
    place that perform the flip — every other module reads/writes in the
    frame named by the field name.

Changelog:
    2026-05-19 (#161/C): Initial — extracted from local_worker.analysis.math.
"""
from __future__ import annotations


def is_white_ply(ply: int) -> bool:
    """Return True iff ``ply`` was played by White.

    Args:
        ply: 1-based ply index. Ply 1 is White's first move.

    Returns:
        True for odd plies (White), False for even plies (Black).
    """
    return ply % 2 == 1


def cp_in_mover_frame(*, white_cp: int, mover_is_white: bool) -> int:
    """Convert a White-frame centipawn value to the mover's frame.

    Args:
        white_cp: Centipawn evaluation in White's frame (positive = White is
            better; negative = Black is better).
        mover_is_white: True iff the side to move is White.

    Returns:
        ``white_cp`` if the mover is White, else ``-white_cp``.
    """
    return white_cp if mover_is_white else -white_cp


def cpl_from_white_cp(
    *, before_white: int, after_white: int, mover_is_white: bool,
) -> int:
    """Centipawn loss in the mover's frame, clamped to non-negative.

    Stockfish emits before/after evaluations in White's frame. Mover-frame
    CPL is the drop in the mover's eval; this function converts both ends
    to the mover's frame and clamps at zero so gains never credit the mover.

    Args:
        before_white: White-frame cp eval *before* the move.
        after_white: White-frame cp eval *after* the move.
        mover_is_white: True iff the side that just moved is White.

    Returns:
        Non-negative integer CPL.
    """
    before_mover = cp_in_mover_frame(white_cp=before_white, mover_is_white=mover_is_white)
    after_mover = cp_in_mover_frame(white_cp=after_white, mover_is_white=mover_is_white)
    return max(0, before_mover - after_mover)
