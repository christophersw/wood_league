"""
Title: _see_helpers.py — Cheapest-legal-attacker selection for SEE
Description:
    Picks the lowest-value piece of a given color that may legally
    capture on the exchange square, filtering pins and pieces that
    have already been cleared from the working occupancy.

Changelog:
    2026-05-09: Initial creation
    2026-05-09: Move minimax reducer to _see_minimax
"""
from __future__ import annotations

import chess

from ._see_targets import PIECE_CP


def _eligible(
    board: chess.Board, sq: int, color: chess.Color, target: int, occupancy: int
) -> int | None:
    """Return the piece value if ``sq`` can legally recapture, else None.

    Args:
        board: Position.
        sq: Candidate attacker square.
        color: Side to move.
        target: Exchange square.
        occupancy: Working occupancy.

    Returns:
        Centipawn value, or None if cleared, wrong color, or pinned off-ray.
    """
    if not (occupancy & chess.BB_SQUARES[sq]):
        return None
    piece = board.piece_at(sq)
    if piece is None or piece.color != color:
        return None
    if target not in board.pin(color, sq):
        return None
    return PIECE_CP[piece.piece_type]


def least_valuable_legal_attacker(
    board: chess.Board,
    attackers_bb: int,
    color: chess.Color,
    target: int,
    occupancy: int,
) -> int | None:
    """Square of the cheapest legal attacker, or None.

    Args:
        board: Position.
        attackers_bb: Candidate attacker bitboard.
        color: Side to move.
        target: Exchange square.
        occupancy: Working occupancy.

    Returns:
        Attacker square, or None if no legal attacker remains.
    """
    pick: tuple[int, int] | None = None
    for sq in chess.SquareSet(attackers_bb):
        val = _eligible(board, sq, color, target, occupancy)
        if val is None:
            continue
        if pick is None or val < pick[0]:
            pick = (val, sq)
    return None if pick is None else pick[1]
