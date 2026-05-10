"""
Title: _windowing.py — Lichess sliding-window volatility helpers
Description:
    Computes the per-ply volatility weights used by game_accuracy(), mirroring
    Lichess AccuracyPercent.scala.  The weight for each ply is the population
    standard deviation of a k-ply window of White-frame Win%, clamped to
    [0.5, 12.0].

    Convention (mirrors Lichess ``allWinPercents``):
      ``all_win_pcts[0]`` = Win% of the initial position (before any move).
      ``all_win_pcts[i]`` = Win% after ply ``i`` (1-based ply, White-frame).
      Length = num_plies + 1.

    Window-size formula: k = clamp(floor(num_plies / 10), 2, 8).
    Front-padding: ply i uses the window starting at max(0, i - (k - 1)).

Changelog:
    2026-05-10: Initial creation — volatility-weight logic extracted from
                math.py to keep per-file Halstead effort under 1000.
"""
from __future__ import annotations

import statistics

_WIN_SIZE_MIN = 2
_WIN_SIZE_MAX = 8
_WEIGHT_FLOOR = 0.5
_WEIGHT_CEIL = 12.0


def lichess_window_size(num_plies: int) -> int:
    """Compute the Lichess sliding-window size for a game with ``num_plies``.

    Formula: k = clamp(floor(num_plies / 10), 2, 8).

    Args:
        num_plies: Total half-moves (plies) in the game.

    Returns:
        Window size in [2, 8].
    """
    return max(_WIN_SIZE_MIN, min(_WIN_SIZE_MAX, num_plies // 10))


def compute_ply_weights(all_win_pcts: list[float]) -> list[float]:
    """Compute clamped per-ply volatility weights for the full game.

    Slides a window of size k over ``all_win_pcts``, taking the population
    standard deviation of each window and clamping to [0.5, 12.0].  The
    front-padding rule (Lichess) assigns ply i the window starting at
    max(0, i - (k - 1)), so early plies reuse the leading window's stddev.

    Args:
        all_win_pcts: White-frame Win% sequence of length num_plies + 1.
            Index 0 = initial position; index i = position after ply i.

    Returns:
        Clamped weight list of length num_plies (one weight per ply).
        Empty if ``all_win_pcts`` has fewer than 2 elements.
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
