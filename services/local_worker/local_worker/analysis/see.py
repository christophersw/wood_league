"""
Title: see.py — Static Exchange Evaluation
Description:
    Computes Static Exchange Evaluation (SEE) for a move, returning the
    net material gain/loss in centipawns for the side initiating the
    capture sequence on the destination square.

    SEE simulates the full exchange — the moving side captures, the
    opponent recaptures with the least valuable legal attacker, and so
    on — minimaxing the running material balance. A move is classified
    as a "capture or sacrifice" iff SEE is strictly negative.

    Edge cases (delegated to ``_see_helpers``):
    - En passant: captured pawn removed from one rank behind the
      destination from the mover's perspective.
    - Promotions: pawn arriving on its back rank is treated as a queen
      for value-on-target; the initial promoting capture absorbs the
      (promo_value - pawn_value) bonus.
    - Absolute pins: attackers pinned to their king are excluded unless
      ``target`` lies on the pin ray.

    Limitation: SEE on positions where the side to move is in check is
    out of scope and handled by the classification layer.

Changelog:
    2026-05-09: Initial creation
    2026-05-09: Add en passant, promotion, and pin edge-case handling
    2026-05-09: Extract helpers to _see_helpers to satisfy quality gate
"""
from __future__ import annotations

import chess

from ._see_minimax import minimax_swap_list
from ._see_swap import run_swap_loop
from ._see_targets import initial_gain_and_target_value, target_square_and_value


def see_value(board: chess.Board, move: chess.Move) -> int:
    """Compute SEE for ``move`` from the moving side's perspective.

    Returns the net centipawn balance after the full exchange on the
    destination square, assuming both sides play the SEE-optimal
    recapture order (cheapest legal attacker first; either side may
    stand pat). Handles en passant, promotions, and absolute pins.

    Args:
        board: Position before the move.
        move: A pseudo-legal move on ``board``.

    Returns:
        Centipawn balance: positive = mover gains, negative = mover
        loses, 0 = even or non-capture.
    """
    captured_sq, captured_value = target_square_and_value(board, move)
    moving = board.piece_at(move.from_square)
    if captured_value == 0 or moving is None:
        return 0

    occupancy = board.occupied
    occupancy &= ~chess.BB_SQUARES[move.from_square]
    occupancy &= ~chess.BB_SQUARES[captured_sq]

    initial_gain, on_target = initial_gain_and_target_value(move, moving, captured_value)
    gain = run_swap_loop(
        board, move.to_square, initial_gain, on_target, occupancy, not board.turn
    )
    return minimax_swap_list(gain)


def see_capture_or_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Return True iff SEE on the destination square is negative.

    Per analysis-math.md, this is the canonical "capture or sacrifice"
    predicate used by the Brilliant classification gate.

    Args:
        board: Position before the move.
        move: The move being played.

    Returns:
        True iff the mover ends the exchange down material.
    """
    return see_value(board, move) < 0
