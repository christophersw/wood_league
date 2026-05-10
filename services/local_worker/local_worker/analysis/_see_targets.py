"""
Title: _see_targets.py — SEE target/value helpers
Description:
    Maps a move to (captured_square, captured_value) and computes the
    value of a piece sitting on a square (queen if a pawn promoted on
    arrival). Pure functions, no exchange logic.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import chess

PIECE_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

_BACK_RANKS = chess.BB_RANK_1 | chess.BB_RANK_8


def target_square_and_value(board: chess.Board, move: chess.Move) -> tuple[int, int]:
    """Return (captured_square, captured_cp_value).

    Args:
        board: Position before the move.
        move: Move under consideration.

    Returns:
        (to_square, 0) for non-captures; for en passant the captured
        pawn's actual square and 100.
    """
    sq = move.to_square
    if board.is_en_passant(move):
        return sq + (-8 if board.turn == chess.WHITE else 8), PIECE_CP[chess.PAWN]
    piece = board.piece_at(sq)
    return (sq, 0) if piece is None else (sq, PIECE_CP[piece.piece_type])


def value_after_landing(piece_type: chess.PieceType, square: int) -> int:
    """Return the value of ``piece_type`` after arriving on ``square``.

    A pawn on its back rank is treated as a queen.

    Args:
        piece_type: Piece type that just moved.
        square: Square the piece arrived on.

    Returns:
        Centipawn value.
    """
    if piece_type == chess.PAWN and chess.BB_SQUARES[square] & _BACK_RANKS:
        return PIECE_CP[chess.QUEEN]
    return PIECE_CP[piece_type]


def initial_gain_and_target_value(
    move: chess.Move, moving: chess.Piece, captured_value: int
) -> tuple[int, int]:
    """Return (swap_list[0], piece_on_target_value) for the initial capture.

    Args:
        move: The capture being analysed.
        moving: The piece making the capture.
        captured_value: Centipawn value of the captured piece.

    Returns:
        Initial swap-list entry and the value sitting on the target.
    """
    if move.promotion is not None:
        on_target = PIECE_CP[move.promotion]
        return captured_value + (on_target - PIECE_CP[chess.PAWN]), on_target
    return captured_value, value_after_landing(moving.piece_type, move.to_square)
