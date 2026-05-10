"""
Title: _accuracy_weight.py — Player weighted-mean accuracy helper
Description:
    Provides ``weighted_mean_accuracy``, which maps a player's per-move
    accuracies to the corresponding per-ply volatility weights and returns
    their weighted average.  Uses the Lichess game-wide weight scheme
    implemented in ``_windowing.compute_ply_weights``.

Changelog:
    2026-05-10: Initial creation — extracted from _windowing.py to keep
                per-file Halstead effort under 1000.
"""
from __future__ import annotations

from ._windowing import _WEIGHT_FLOOR, compute_ply_weights


def weighted_mean_accuracy(
    move_accuracies: list[float],
    all_win_pcts: list[float],
    mover_ply_indices: list[int],
) -> float:
    """Volatility-weighted mean accuracy for one player.

    Extracts per-ply weights from the game-wide Win% sequence and returns the
    weighted average of this player's move accuracies.  Falls back to the
    arithmetic mean if the total weight is zero.

    Args:
        move_accuracies: Per-move accuracy values for this player (0-100).
            Length must equal ``len(mover_ply_indices)``.
        all_win_pcts: White-frame Win% for the whole game, length=num_plies+1.
            Index 0 = initial position; index i = eval after ply i.
        mover_ply_indices: 0-based indices into ``all_win_pcts`` for the plies
            played by this player.  White: [1, 3, 5, ...]; Black: [2, 4, 6, ...].

    Returns:
        Weighted mean accuracy, or 0.0 if ``move_accuracies`` is empty.

    Raises:
        ValueError: If ``move_accuracies`` and ``mover_ply_indices`` differ in
            length.
    """
    n = len(move_accuracies)
    if n == 0:
        return 0.0
    if n != len(mover_ply_indices):
        raise ValueError(
            f"move_accuracies (len={n}) and mover_ply_indices "
            f"(len={len(mover_ply_indices)}) must have equal length"
        )

    ply_weights = compute_ply_weights(all_win_pcts)
    num_weights = len(ply_weights)
    player_weights = [
        ply_weights[idx - 1] if 0 < idx <= num_weights else _WEIGHT_FLOOR
        for idx in mover_ply_indices
    ]
    total = sum(player_weights)
    if total <= 0.0:
        return sum(move_accuracies) / n
    return sum(w * a for w, a in zip(player_weights, move_accuracies)) / total
