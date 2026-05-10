"""
Title: _see_minimax.py — SEE swap-list minimax reducer
Description:
    Reduces a SEE swap list to its final balance.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations


def minimax_swap_list(gain: list[int]) -> int:
    """Reduce a SEE swap list to its minimax value.

    Args:
        gain: Swap-list entries appended during the exchange.

    Returns:
        Final balance from the initiator's perspective.
    """
    while len(gain) > 1:
        gain[-2] = -max(-gain[-2], gain[-1])
        gain.pop()
    return gain[0]
