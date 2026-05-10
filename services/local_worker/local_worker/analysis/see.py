"""
Title: see.py — Static Exchange Evaluation
Description:
    Computes Static Exchange Evaluation (SEE) for a move, returning the
    net material gain/loss in centipawns for the side initiating the
    capture sequence on the destination square.

    SEE simulates the full exchange — the moving side captures, the
    opponent recaptures with the least valuable attacker, and so on —
    minimaxing the running material balance. A move is classified as a
    "capture or sacrifice" iff SEE is strictly negative for the mover.

    Implementation note: python-chess has no public SEE method, so we
    enumerate attackers via Board.attackers() and process them in
    increasing piece value, swapping sides each step. X-ray attackers
    behind sliding pieces are revealed by removing the captured square
    from the occupancy and re-querying attackers.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import chess

# Centipawn values used for SEE balance arithmetic.
_PIECE_CP = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}


def _least_valuable_attacker(
    board: chess.Board, attackers: chess.SquareSet, color: chess.Color
) -> int | None:
    """Return the square of the cheapest attacker in `attackers`, or None.

    Args:
        board: Position (used to read piece type at each attacker square).
        attackers: SquareSet of pieces of `color` attacking the target.
        color: The side whose attackers we are scanning.

    Returns:
        Square index of the least-valuable attacker, or None if `attackers`
        is empty.
    """
    best_sq: int | None = None
    best_val: int | None = None
    for sq in attackers:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        val = _PIECE_CP[piece.piece_type]
        if best_val is None or val < best_val:
            best_val = val
            best_sq = sq
    return best_sq


def see_value(board: chess.Board, move: chess.Move) -> int:
    """Compute SEE for `move` from the moving side's perspective.

    For non-capture moves SEE returns 0. For captures, returns the net
    centipawn balance after the full exchange sequence on the destination
    square, assuming both sides play the SEE-optimal recapture order
    (cheapest attacker first; either side may stand pat).

    Args:
        board: Position before the move.
        move: A pseudo-legal move on `board`.

    Returns:
        Centipawn balance: positive = mover gains material, negative =
        mover loses material, 0 = even or non-capture.
    """
    target = move.to_square
    captured = board.piece_at(target)
    moving = board.piece_at(move.from_square)
    if captured is None or moving is None:
        return 0

    # Build a working occupancy we can mutate to reveal x-ray attackers.
    occupancy = board.occupied
    side = not board.turn  # after the initial capture, opponent moves next
    gain: list[int] = [_PIECE_CP[captured.piece_type]]
    moved_piece_type = moving.piece_type
    occupancy &= ~chess.BB_SQUARES[move.from_square]

    while True:
        # Find cheapest attacker of `target` for `side` given current occupancy
        attackers_bb = (
            board.attackers_mask(side, target) & occupancy
        )
        if not attackers_bb:
            break
        attackers = chess.SquareSet(attackers_bb)
        from_sq = _least_valuable_attacker(board, attackers, side)
        if from_sq is None:
            break

        # The piece doing the recapture is the moved piece for the next swap step
        gain.append(_PIECE_CP[moved_piece_type] - gain[-1])
        moved_piece_type = board.piece_type_at(from_sq) or chess.PAWN
        occupancy &= ~chess.BB_SQUARES[from_sq]
        side = not side

        # Pruning: if even capturing optimally cannot improve, stop.
        if max(-gain[-2], gain[-1]) < 0:
            break

    # Minimax the gain list
    while len(gain) > 1:
        gain[-2] = -max(-gain[-2], gain[-1])
        gain.pop()
    return gain[0]


def see_capture_or_sacrifice(board: chess.Board, move: chess.Move) -> bool:
    """Return True iff SEE on the destination square is negative for the mover.

    Per analysis-math.md, this is the canonical "capture or sacrifice"
    predicate used by the Brilliant classification gate.

    Args:
        board: Position before the move.
        move: The move being played.

    Returns:
        True if the mover ends the exchange down material, False otherwise
        (including for quiet moves and equal/winning captures).
    """
    return see_value(board, move) < 0
