"""
Title: _stockfish_helpers.py — Internal helpers for Stockfish per-move analysis
Description:
    Conversion helpers for the Stockfish pipeline: White-frame cp
    extraction, mover-frame projection, second-best gap from a multi-PV
    result, and combined CPL (regular + mate-distance penalty).

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

from typing import Optional

import chess
import chess.engine

from ._mate_distance import mate_distance_cpl, mover_mate
from .math import MATE_SCORE, cpl_from_evals


def white_cp(score: chess.engine.PovScore) -> int:
    """Return the cp evaluation from White's frame, mate flattened.

    Args:
        score: PovScore from engine analysis.

    Returns:
        cp value in [-MATE_SCORE, MATE_SCORE].
    """
    return score.pov(chess.WHITE).score(mate_score=MATE_SCORE)


def mover_cp(eval_white: int, mover: chess.Color) -> int:
    """Flip a White-frame cp eval to the mover's perspective.

    Args:
        eval_white: cp from White's frame.
        mover: Side whose perspective we want.

    Returns:
        cp from the mover's frame.
    """
    return eval_white if mover == chess.WHITE else -eval_white


def second_best_gap(
    info_before: list, mover_eval_before: int, mover: chess.Color
) -> Optional[int]:
    """cp gap between best and second-best PV in the mover's frame.

    Args:
        info_before: Multi-PV list from the position before the move.
        mover_eval_before: Best-PV cp already converted to mover frame.
        mover: Side to move.

    Returns:
        Gap in cp, or None if MultiPV did not produce a second line.
    """
    if len(info_before) < 2:
        return None
    return mover_eval_before - mover_cp(white_cp(info_before[1]["score"]), mover)


def total_cpl(
    info_before: list,
    info_after: dict,
    eval_before_white: int,
    eval_after_white: int,
    mover: chess.Color,
) -> int:
    """Combine regular CPL with the mate-distance penalty.

    Args:
        info_before: PV list from the position before the move.
        info_after: PV dict from the position after the move.
        eval_before_white: cp before, White frame.
        eval_after_white: cp after, White frame.
        mover: Side to move.

    Returns:
        Total CPL.
    """
    base = cpl_from_evals(
        eval_before_white, eval_after_white, mover_is_white=(mover == chess.WHITE)
    )
    extra = mate_distance_cpl(
        mover_mate(info_before[0]["score"], mover),
        mover_mate(info_after["score"], mover),
    )
    return base + extra
