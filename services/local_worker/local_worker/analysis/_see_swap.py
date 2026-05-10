"""
Title: _see_swap.py — SEE swap-loop driver
Description:
    Runs the iterative cheapest-legal-attacker recapture loop, building
    the swap list consumed by the minimax reducer.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import chess

from ._see_helpers import least_valuable_legal_attacker
from ._see_targets import value_after_landing


def run_swap_loop(
    board: chess.Board,
    target: int,
    initial_gain: int,
    on_target: int,
    occupancy: int,
    side: chess.Color,
) -> list[int]:
    """Run the SEE swap loop and return the unreduced swap list.

    Each step: cheapest legal attacker for ``side`` recaptures on
    ``target``; the piece is removed from ``occupancy`` and the value
    sitting on ``target`` updates (a pawn promotes to queen on its back
    rank). Loop ends when no legal attacker remains or pruning shows no
    further improvement is possible.

    Args:
        board: Position (read-only).
        target: Exchange square.
        initial_gain: Material gained by the first capture.
        on_target: Value of the piece on ``target`` after the first capture.
        occupancy: Working occupancy (mover/captured already cleared).
        side: Side to move (the original mover's opponent).

    Returns:
        Swap list ready for minimax reduction.
    """
    gain = [initial_gain]
    while True:
        bb = board.attackers_mask(side, target, occupancy)
        if not bb:
            break
        from_sq = least_valuable_legal_attacker(board, bb, side, target, occupancy)
        if from_sq is None:
            break
        gain.append(on_target - gain[-1])
        piece_type = board.piece_type_at(from_sq) or chess.PAWN
        occupancy &= ~chess.BB_SQUARES[from_sq]
        on_target = value_after_landing(piece_type, target)
        side = not side
        if max(-gain[-2], gain[-1]) < 0:
            break
    return gain
