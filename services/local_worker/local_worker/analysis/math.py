"""
Title: math.py — Chess analysis math formulas
Description:
    Implements every formula in services/app/documentation/analysis-math.md:
    Win% (sigmoid), per-move accuracy, mover-perspective CPL, windowed-stddev
    weighted game accuracy, harmonic-mean game accuracy, Stockfish CPL-based
    classification, Lc0 ΔWin%-based classification, and Lc0 Q→cp conversion.

    Numeric constants and ordering match the spec exactly. Do not change them
    to match a different implementation.

    Game accuracy uses the Lichess-aligned volatility-windowing scheme from
    _windowing.py. See that module and analysis-math.md for the full spec.

Changelog:
    2026-05-09: Initial creation
    2026-05-10: game_accuracy() updated to Lichess game-wide windowing scheme;
                old per-player fixed-window logic removed. New API uses
                all_win_pcts + mover_ply_indices instead of per-player win_pcts.
"""
from __future__ import annotations

import math
from typing import Optional

from ._accuracy_weight import weighted_mean_accuracy

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


def game_accuracy(
    move_accuracies: list[float],
    *,
    all_win_pcts: list[float],
    mover_ply_indices: list[int],
) -> float:
    """Game accuracy = (volatility-weighted mean + harmonic mean) / 2.

    Implements the Lichess AccuracyPercent.scala scheme.  Inputs use
    White-frame, game-wide Win% so that window volatility is computed across
    the full interleaved move sequence rather than per-player subsequences.

    Win% convention (mirrors Lichess ``allWinPercents``):
        ``all_win_pcts[0]`` = Win% of the initial position (before any move).
        ``all_win_pcts[i]`` = Win% after ply ``i`` (1-based ply).
        Length = num_plies + 1.

    Window-size formula: k = clamp(floor(num_plies / 10), 2, 8).
    Front-padding: the first k-2 plies receive the same weight as ply k-1
    (their window starts at index 0 of all_win_pcts, identical to ply k-1's
    window).
    Weight clamp: [0.5, 12.0].

    Harmonic mean clamps each accuracy at ε=0.001 to avoid zero-division and
    to penalise severe blunders.

    Args:
        move_accuracies: Per-move accuracy values for this player (0–100 each).
            Length must equal ``len(mover_ply_indices)``.
        all_win_pcts: White-frame Win% for the whole game.  Index 0 is the
            initial position eval; index i is the eval after ply i.
            Length = num_plies + 1.
        mover_ply_indices: 0-based indices into ``all_win_pcts`` of the plies
            played by this player.  White: [1, 3, 5, …]; Black: [2, 4, 6, …].

    Returns:
        Game accuracy in [0, 100].  Returns 0.0 if ``move_accuracies`` is
        empty.

    Raises:
        ValueError: If ``move_accuracies`` and ``mover_ply_indices`` differ in
            length.
    """
    if not move_accuracies:
        return 0.0
    n = len(move_accuracies)

    harmonic = n / sum(1.0 / max(a, _HARMONIC_EPSILON) for a in move_accuracies)
    weighted_mean = weighted_mean_accuracy(move_accuracies, all_win_pcts, mover_ply_indices)

    return max(0.0, min(100.0, (weighted_mean + harmonic) / 2.0))


def _top_tier(
    *,
    second_best_gap: Optional[float],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
    brilliant_gap: float,
    great_gap: float,
    winpct_ceiling: float,
) -> str:
    """Resolve Brilliant / Great / Best for a move in the top quality bucket.

    Args:
        second_best_gap: Gap between best and second-best move (cp or Win%).
        mover_win_pct: Win% for the mover before the move.
        is_capture_or_sacrifice: SEE-based capture/sacrifice flag.
        brilliant_gap: Threshold gap qualifying for Brilliant.
        great_gap: Threshold gap qualifying for Great.
        winpct_ceiling: Mover Win% must be below this for Brilliant.

    Returns:
        "Brilliant", "Great", or "Best".
    """
    if second_best_gap is None:
        return "Best"
    if (
        second_best_gap >= brilliant_gap
        and mover_win_pct < winpct_ceiling
        and is_capture_or_sacrifice
    ):
        return "Brilliant"
    if second_best_gap >= great_gap:
        return "Great"
    return "Best"


def classify_stockfish_move(
    *,
    cpl: int,
    second_best_gap: Optional[int],
    mover_win_pct: float,
    is_capture_or_sacrifice: bool,
) -> str:
    """Classify a Stockfish move per analysis-math.md (first match wins).

    Order: Brilliant → Great → Best → Excellent → Inaccuracy → Mistake → Blunder.
    `is_capture_or_sacrifice` must be the SEE-based determination.

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
        return _top_tier(
            second_best_gap=second_best_gap,
            mover_win_pct=mover_win_pct,
            is_capture_or_sacrifice=is_capture_or_sacrifice,
            brilliant_gap=_SF_BRILLIANT_GAP,
            great_gap=_SF_GREAT_GAP,
            winpct_ceiling=_SF_BRILLIANT_WINPCT_CEILING,
        )
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
    if delta_win_pct <= _LC0_EXCELLENT_MIN:
        return _top_tier(
            second_best_gap=second_best_gap,
            mover_win_pct=mover_win_pct,
            is_capture_or_sacrifice=is_capture_or_sacrifice,
            brilliant_gap=_LC0_BRILLIANT_GAP,
            great_gap=_LC0_GREAT_GAP,
            winpct_ceiling=_LC0_BRILLIANT_WINPCT_CEILING,
        )
    if delta_win_pct < _LC0_INACCURACY_MIN:
        return "Excellent"
    if delta_win_pct < _LC0_MISTAKE_MIN:
        return "Inaccuracy"
    if delta_win_pct < _LC0_BLUNDER_MIN:
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
