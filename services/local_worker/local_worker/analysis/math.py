"""
Title: math.py — Chess analysis math formulas
Description:
    Implements every formula in services/app/documentation/analysis-math.md:
    Win% (sigmoid), per-move accuracy, mover-perspective CPL, windowed-stddev
    weighted game accuracy, harmonic-mean game accuracy, Stockfish CPL-based
    classification, Lc0 ΔWin%-based classification, and Lc0 Q→cp conversion.

    Numeric constants and ordering match the spec exactly. Do not change them
    to match a different implementation.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

MATE_SCORE = 10000

# Stockfish CPL classification thresholds (analysis-math.md)
_SF_EXCELLENT_CPL = 10
_SF_INACCURACY_CPL = 50
_SF_MISTAKE_CPL = 100
_SF_BLUNDER_CPL = 300
_SF_BRILLIANT_GAP = 150
_SF_GREAT_GAP = 80
_SF_BRILLIANT_WINPCT_CEILING = 70.0

# Lc0 ΔWin% classification thresholds (analysis-math.md)
_LC0_EXCELLENT_MIN = 1.0   # exclusive
_LC0_INACCURACY_MIN = 2.0  # inclusive
_LC0_MISTAKE_MIN = 5.0     # inclusive
_LC0_BLUNDER_MIN = 10.0    # inclusive
_LC0_BRILLIANT_GAP = 10.0
_LC0_GREAT_GAP = 6.0
_LC0_BRILLIANT_WINPCT_CEILING = 70.0

# Game-accuracy aggregation
_WINDOW_SIZE = 8
_HARMONIC_EPSILON = 0.001

# Lc0 Q → cp conversion constants (precise values from spec)
_Q_CP_SCALE = 111.714640912
_Q_CP_INNER = 1.5620688421


def win_pct(cp: float) -> float:
    """Win% from cp evaluation, using the Lichess sigmoid.

    Args:
        cp: Centipawn evaluation from the mover's perspective. Mate scores
            are passed in as ±MATE_SCORE (10000) — the sigmoid saturates
            naturally at those values.

    Returns:
        Win probability as a percentage (0–100).
    """
    return 100.0 / (1.0 + math.exp(-0.00368208 * cp))


def move_accuracy(win_pct_before: float, win_pct_after: float) -> float:
    """Per-move accuracy from the mover's Win% drop.

    Formula (analysis-math.md):
        Accuracy% = 103.1668100711649 · exp(-0.04354415386753951 · drop)
                    - 3.166924740191411
    Result clamped to [0, 100]. There is *no* trailing `+ 1` term — that
    was present in the legacy implementation and has been removed.

    Args:
        win_pct_before: Win% for the mover before the move (0–100).
        win_pct_after: Win% for the mover after the move (0–100).

    Returns:
        Accuracy in [0, 100].
    """
    drop = win_pct_before - win_pct_after
    acc = (
        103.1668100711649 * math.exp(-0.04354415386753951 * drop)
        - 3.166924740191411
    )
    return max(0.0, min(100.0, acc))


def cpl_from_evals(eval_before_cp: int, eval_after_cp: int, *, mover_is_white: bool) -> int:
    """Compute CPL from before/after cp evaluations expressed in White's frame.

    Stockfish reports cp from White's perspective. To compute CPL from the
    mover's perspective, Black's evaluations must be negated first.

    Args:
        eval_before_cp: cp evaluation before the move, White's perspective.
        eval_after_cp: cp evaluation after the move, White's perspective.
        mover_is_white: True if the side to move was White.

    Returns:
        CPL as a non-negative integer (clamped at 0 — the mover is never
        credited with negative loss).
    """
    if mover_is_white:
        before_mover = eval_before_cp
        after_mover = eval_after_cp
    else:
        before_mover = -eval_before_cp
        after_mover = -eval_after_cp
    return max(0, before_mover - after_mover)


def _windowed_std(values: list[float], center: int, window: int) -> float:
    """Standard deviation of `values` in a window of size `window` centered on
    index `center`, truncated at sequence boundaries.

    Args:
        values: Numeric sequence.
        center: Center index.
        window: Window size (e.g., 8).

    Returns:
        Population standard deviation. Returns 0.0 if the window contains
        fewer than 2 samples.
    """
    half = window // 2
    lo = max(0, center - half)
    hi = min(len(values), center + half + (window % 2))
    sample = values[lo:hi]
    if len(sample) < 2:
        return 0.0
    return statistics.pstdev(sample)


def game_accuracy(move_accuracies: list[float], *, win_pcts: list[float]) -> float:
    """Game accuracy = (windowed-stddev weighted mean + harmonic mean) / 2.

    Both inputs must be **per-player** sequences (only the moves made by the
    player being evaluated, in order). They must be the same length.

    The weighted mean weights each move by the population standard deviation
    of Win% across a window of size 8 centered on that move (truncated at
    boundaries) — moves played in volatile positions count more.

    The harmonic mean clamps each accuracy at ε=0.001 to avoid division by
    zero and to penalize severe blunders.

    Args:
        move_accuracies: Per-player accuracy values, one per move (0–100 each).
        win_pcts: Per-player Win% values aligned with move_accuracies — these
            are the Win% values *before* each of the player's moves, used to
            compute volatility weights.

    Returns:
        Game accuracy in [0, 100]. Returns 0.0 if the list is empty.

    Raises:
        ValueError: If the two input lists differ in length.
    """
    if not move_accuracies:
        return 0.0
    if len(move_accuracies) != len(win_pcts):
        raise ValueError(
            f"move_accuracies (len={len(move_accuracies)}) and "
            f"win_pcts (len={len(win_pcts)}) must have equal length"
        )
    n = len(move_accuracies)

    harmonic = n / sum(1.0 / max(a, _HARMONIC_EPSILON) for a in move_accuracies)

    weights = [_windowed_std(win_pcts, i, _WINDOW_SIZE) for i in range(n)]
    total_weight = sum(weights)
    if total_weight <= 0.0:
        # Degenerate case (e.g., constant Win%) — fall back to arithmetic mean
        weighted_mean = sum(move_accuracies) / n
    else:
        weighted_mean = sum(w * a for w, a in zip(weights, move_accuracies)) / total_weight

    return max(0.0, min(100.0, (weighted_mean + harmonic) / 2.0))


def classify_stockfish_move(
    *,
    cpl: int,
    second_best_gap: Optional[int],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify a Stockfish move per analysis-math.md (first match wins).

    Order: Brilliant → Great → Best → Excellent → Inaccuracy → Mistake → Blunder.
    `is_capture_or_sacrifice` must be the SEE-based determination (see
    `analysis/see.py`).

    Args:
        cpl: Centipawn loss (≥0) for this move from the mover's perspective.
        second_best_gap: cp gap between the best and second-best legal moves
            from the position before the move. None if MultiPV ≥ 2 was not
            available.
        mover_win_pct: Win% for the mover before the move (0–100).
        is_capture_or_sacrifice: True iff SEE on the destination square is
            negative for the mover.

    Returns:
        One of: Brilliant, Great, Best, Excellent, Inaccuracy, Mistake, Blunder.
    """
    if cpl < _SF_EXCELLENT_CPL:
        if (
            second_best_gap is not None
            and second_best_gap >= _SF_BRILLIANT_GAP
            and mover_win_pct < _SF_BRILLIANT_WINPCT_CEILING
            and is_capture_or_sacrifice
        ):
            return "Brilliant"
        if second_best_gap is not None and second_best_gap >= _SF_GREAT_GAP:
            return "Great"
        return "Best"
    if cpl < _SF_INACCURACY_CPL:
        return "Excellent"
    if cpl < _SF_MISTAKE_CPL:
        return "Inaccuracy"
    if cpl < _SF_BLUNDER_CPL:
        return "Mistake"
    return "Blunder"


def classify_lc0_move(
    *,
    delta_win_pct: float,
    second_best_gap: Optional[float],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify an Lc0 move per analysis-math.md (first match wins).

    Order: Brilliant → Great → Best → Excellent → Inaccuracy → Mistake → Blunder.

    Args:
        delta_win_pct: Win% loss from the mover's perspective (≥0).
        second_best_gap: Win% gap between best and second-best move from the
            position before the move. None if unavailable.
        mover_win_pct: Win% for the mover before the move (0–100).
        is_capture_or_sacrifice: True iff SEE on the destination square is
            negative for the mover.

    Returns:
        One of: Brilliant, Great, Best, Excellent, Inaccuracy, Mistake, Blunder.
    """
    if delta_win_pct <= _LC0_EXCELLENT_MIN:  # Δ ≤ 1%
        if (
            second_best_gap is not None
            and second_best_gap >= _LC0_BRILLIANT_GAP
            and mover_win_pct < _LC0_BRILLIANT_WINPCT_CEILING
            and is_capture_or_sacrifice
        ):
            return "Brilliant"
        if second_best_gap is not None and second_best_gap >= _LC0_GREAT_GAP:
            return "Great"
        return "Best"
    if delta_win_pct < _LC0_INACCURACY_MIN:   # 1% < Δ < 2%
        return "Excellent"
    if delta_win_pct < _LC0_MISTAKE_MIN:      # 2% ≤ Δ < 5%
        return "Inaccuracy"
    if delta_win_pct < _LC0_BLUNDER_MIN:      # 5% ≤ Δ < 10%
        return "Mistake"
    return "Blunder"                          # Δ ≥ 10%


def cp_equiv_from_q(q: float) -> int:
    """Convert an Lc0 Q value to its centipawn equivalent.

    Formula (analysis-math.md):
        cp_equiv = 111.714640912 · tan(1.5620688421 · Q)

    Q is clamped to (-0.9999999, 0.9999999) to avoid the tangent singularity
    at ±1.

    Args:
        q: Lc0 Q value in (-1, 1).

    Returns:
        Integer centipawn equivalent.
    """
    q_clamped = max(-0.9999999, min(0.9999999, q))
    return round(_Q_CP_SCALE * math.tan(_Q_CP_INNER * q_clamped))
