"""
Title: accuracy.py — Win% sigmoid + per-move/game accuracy aggregation
Description:
    Issue #161 Phase C. Consolidates the Lichess win%-curve and accuracy math
    that previously lived in ``local_worker.analysis.math`` and
    ``local_worker.analysis._accuracy_weight`` / ``_windowing``.

    Three layers:
      * ``win_pct(cp)`` — sigmoid Win% from a centipawn evaluation.
      * ``move_accuracy(before, after)`` — per-ply accuracy from the mover's
        Win% drop, clamped to [0, 100].
      * ``game_accuracy(...)`` — Lichess-aligned volatility-windowed weighted
        mean averaged with the harmonic mean.

    Numeric constants mirror ``analysis-math.md`` exactly. Do NOT retune here
    to match an implementation; tune the spec, then this file.

Changelog:
    2026-05-19 (#161/C): Initial — ported from local_worker.analysis.{math,_windowing,_accuracy_weight}.
"""
from __future__ import annotations

import math
import statistics

# ── Win% sigmoid ────────────────────────────────────────────────────────
# Lichess WinPercent.scala coefficient.
_WIN_PCT_K = 0.00368208

# ── Move accuracy ───────────────────────────────────────────────────────
# Lichess AccuracyPercent.scala coefficients.
_ACC_SCALE = 103.1668100711649
_ACC_RATE = 0.04354415386753951
_ACC_OFFSET = 3.166924740191411

# ── Game accuracy: harmonic + windowing ─────────────────────────────────
_HARMONIC_EPSILON = 0.001
_WIN_SIZE_MIN = 2
_WIN_SIZE_MAX = 8
_WEIGHT_FLOOR = 0.5
_WEIGHT_CEIL = 12.0


def win_pct(cp: float) -> float:
    """Win% from a centipawn evaluation using the Lichess sigmoid.

    Args:
        cp: Centipawn evaluation in the mover's frame. Mate scores can be
            passed as ±10000; the sigmoid saturates naturally.

    Returns:
        Win probability as a percentage in (0, 100).
    """
    return 100.0 / (1.0 + math.exp(-_WIN_PCT_K * cp))


def move_accuracy(win_pct_before: float, win_pct_after: float) -> float:
    """Per-move accuracy from the mover's Win% drop.

    Formula (analysis-math.md)::

        accuracy = 103.1668 · exp(-0.04354 · drop) - 3.1669

    Clamped to [0, 100]. There is no trailing ``+ 1`` term — that was present
    in the legacy implementation and has been removed.

    Args:
        win_pct_before: Mover's Win% before the move (0-100).
        win_pct_after: Mover's Win% after the move (0-100).

    Returns:
        Accuracy in [0, 100].
    """
    drop = win_pct_before - win_pct_after
    raw = _ACC_SCALE * math.exp(-_ACC_RATE * drop) - _ACC_OFFSET
    return max(0.0, min(100.0, raw))


def lichess_window_size(num_plies: int) -> int:
    """Lichess volatility-window size for a game with ``num_plies`` half-moves.

    Args:
        num_plies: Total half-moves in the game.

    Returns:
        ``clamp(num_plies // 10, 2, 8)``.
    """
    return max(_WIN_SIZE_MIN, min(_WIN_SIZE_MAX, num_plies // 10))


def _compute_ply_weights(all_win_pcts: list[float]) -> list[float]:
    """Per-ply volatility weights computed from the game-wide Win% sequence.

    Slides a k-ply window over ``all_win_pcts`` and uses the population stddev
    of each window as the weight, clamped to [0.5, 12.0]. Front-padding maps
    early plies onto the leading window (per Lichess).

    Args:
        all_win_pcts: White-frame Win% sequence of length ``num_plies + 1``.

    Returns:
        Clamped weight list of length ``num_plies`` (empty for trivial input).
    """
    num_plies = len(all_win_pcts) - 1
    if num_plies <= 0:
        return []
    k = lichess_window_size(num_plies)
    weights: list[float] = []
    for j in range(num_plies):
        start = max(0, j + 1 - (k - 1))
        window = all_win_pcts[start : start + k]
        raw = statistics.pstdev(window) if len(window) >= 2 else 0.0
        weights.append(max(_WEIGHT_FLOOR, min(_WEIGHT_CEIL, raw)))
    return weights


def _weighted_mean(
    move_accuracies: list[float],
    all_win_pcts: list[float],
    mover_ply_indices: list[int],
) -> float:
    """Volatility-weighted mean of one player's per-move accuracies."""
    ply_weights = _compute_ply_weights(all_win_pcts)
    num_weights = len(ply_weights)
    player_weights = [
        ply_weights[idx - 1] if 0 < idx <= num_weights else _WEIGHT_FLOOR
        for idx in mover_ply_indices
    ]
    total = sum(player_weights)
    if total <= 0.0:
        return sum(move_accuracies) / len(move_accuracies)
    return sum(w * a for w, a in zip(player_weights, move_accuracies)) / total


def game_accuracy(
    move_accuracies: list[float],
    *,
    all_win_pcts: list[float],
    mover_ply_indices: list[int],
) -> float:
    """Game accuracy = (volatility-weighted mean + harmonic mean) / 2.

    Mirrors Lichess ``AccuracyPercent.scala``. Inputs use White-frame, game-wide
    Win% so windowing covers the full interleaved move sequence.

    Args:
        move_accuracies: This player's per-move accuracy values (0-100).
        all_win_pcts: White-frame Win% sequence (length = num_plies + 1).
        mover_ply_indices: 0-based indices into ``all_win_pcts`` for this
            player's plies. White: [1, 3, 5, …]; Black: [2, 4, 6, …].

    Returns:
        Game accuracy in [0, 100]; 0.0 if ``move_accuracies`` is empty.

    Raises:
        ValueError: When ``move_accuracies`` and ``mover_ply_indices`` differ
            in length.
    """
    n = len(move_accuracies)
    if n == 0:
        return 0.0
    if n != len(mover_ply_indices):
        raise ValueError(
            f"move_accuracies (len={n}) and mover_ply_indices "
            f"(len={len(mover_ply_indices)}) must have equal length"
        )
    harmonic = n / sum(1.0 / max(a, _HARMONIC_EPSILON) for a in move_accuracies)
    weighted = _weighted_mean(move_accuracies, all_win_pcts, mover_ply_indices)
    return max(0.0, min(100.0, (weighted + harmonic) / 2.0))
