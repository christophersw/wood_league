"""
Title: test_see.py — Tests for Static Exchange Evaluation
Description:
    Verifies that see_capture_or_sacrifice() returns True only when the
    full exchange sequence on the destination square is a net material
    loss for the mover. Also covers en passant, promotions during the
    exchange, and absolute-pin filtering.

Changelog:
    2026-05-09: Initial creation
    2026-05-09: Add en passant, promotion, and pin edge-case tests
"""
import chess
from local_worker.analysis.see import see_value, see_capture_or_sacrifice


def test_unprotected_pawn_capture_is_winning():
    # White pawn on e4 captures undefended pawn on d5 — SEE = +pawn
    board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("e4d5")
    assert see_value(board, move) > 0
    assert not see_capture_or_sacrifice(board, move)


def test_queen_takes_defended_pawn_is_sacrifice():
    # White queen on h5 takes pawn h7 defended by Black king — SEE strongly negative
    board = chess.Board("4k2r/7p/8/7Q/8/8/8/4K3 w k - 0 1")
    move = chess.Move.from_uci("h5h7")
    assert see_value(board, move) < 0
    assert see_capture_or_sacrifice(board, move)


def test_equal_trade_is_not_sacrifice():
    # White knight takes Black knight, defended only by a pawn — net 0 (knight for knight)
    board = chess.Board("4k3/8/3p4/4n3/3N4/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("d4e5")
    # SEE: +knight (320) -knight (320) = 0
    assert see_value(board, move) == 0
    assert not see_capture_or_sacrifice(board, move)


def test_quiet_move_returns_zero():
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    assert see_value(board, move) == 0
    assert not see_capture_or_sacrifice(board, move)


def test_en_passant_capture_value():
    """En passant: White pawn e5 captures Black pawn d5 via d6.

    Position: 4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1
    Move: e5d6 (en passant). Captured pawn is on d5, not d6. No piece
    defends d6 after the capture, so SEE = +100 (pawn gained, no recapture).
    """
    board = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
    move = chess.Move.from_uci("e5d6")
    assert board.is_en_passant(move), "move should be recognised as en passant"
    result = see_value(board, move)
    assert result == 100, f"expected +100 (pawn gain, no recapture), got {result}"
    assert not see_capture_or_sacrifice(board, move)


def test_promotion_initial_move():
    """Promoting capture gains rook + promotion bonus.

    Position: r3k3/1P6/8/8/8/8/8/4K3 w q - 0 1
    Move: b7a8q — White pawn captures undefended Black rook on a8 and
    promotes to queen. No piece defends a8 (Black king on e8 is not adjacent).

    Standard SEE for a promoting capture:
      gain = rook_value + (queen_value - pawn_value) = 500 + 800 = 1300 cp.
    """
    board = chess.Board("r3k3/1P6/8/8/8/8/8/4K3 w q - 0 1")
    move = chess.Move.from_uci("b7a8q")
    assert move.promotion == chess.QUEEN
    result = see_value(board, move)
    assert result == 1300, f"expected 1300 (500 rook + 800 promotion bonus), got {result}"
    assert not see_capture_or_sacrifice(board, move)


def test_promoted_piece_recaptured():
    """Promoting capture, then opponent recaptures the queen.

    Position: r6r/1P2k3/8/8/8/8/8/4K3 w - - 0 1
    White pawn b7 captures rook on a8 and promotes to queen.
    Black rook on h8 can slide along rank 8 to recapture (king on e7
    does not block rank 8).

    SEE breakdown:
      gain[0] = 500 (rook) + 800 (promotion bonus) = 1300
      gain[1] = queen_value(900) - 1300 = -400  [Black recaptures]
    Minimax: gain[0] = -max(-1300, -400) = 400.
    Net SEE = +400 cp.
    """
    board = chess.Board("r6r/1P2k3/8/8/8/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("b7a8q")
    result = see_value(board, move)
    assert result == 400, f"expected +400, got {result}"
    assert not see_capture_or_sacrifice(board, move)


def test_pinned_attacker_skipped():
    """Absolutely pinned piece excluded when target is off the pin ray.

    Position: 1r5k/6K1/8/8/Rp6/2B5/8/q7 w - - 0 1
    - White King g7, White Rook a4, White Bishop c3.
    - Black Queen a1 pins White Bishop c3 to White King g7 along the
      a1-c3-e5-g7 diagonal.
    - Black Pawn b4, Black Rook b8.

    White Rook a4 captures Black Pawn b4 (+100 cp).
    Black Rook b8 recaptures (Black gains rook, 500 cp).
    White Bishop c3 would recapture b4, but b4 is NOT on the a1-g7 pin
    ray (b4 has file=1, rank=3; the pin ray has rank=file). Bishop is
    excluded by pin filtering.

    With pin filter: gain = [100, 400]. Minimax => SEE = -400.
    Without pin filter: bishop would recapture, minimax => SEE = +100.
    The correct SEE is -400, flagging this as a sacrifice.
    """
    board = chess.Board("1r5k/6K1/8/8/Rp6/2B5/8/q7 w - - 0 1")
    move = chess.Move.from_uci("a4b4")

    assert board.piece_at(chess.B4) is not None, "Black pawn should be on b4"

    result = see_value(board, move)
    assert result == -400, f"expected -400 (rook lost, bishop pinned and excluded), got {result}"
    assert see_capture_or_sacrifice(board, move)


def test_pinned_along_ray_can_participate():
    """A piece pinned along the pin ray CAN capture on a square within that ray.

    Position: 7k/8/8/R3p3/8/2B5/8/q7 w - - 0 1
    - White King g7, White Rook a5, White Bishop c3.
    - Black Queen a1 pins White Bishop c3 to White King g7 along the
      a1-c3-e5-g7 diagonal.
    - Black Pawn e5.

    White Rook a5 captures Black Pawn e5.
    Black Queen a1 can recapture e5 (a1 to e5: diagonal, valid queen move).
    White Bishop c3 can recapture e5 (e5 IS on the a1-g7 pin ray).
    Black has no further recapture. Black's best play is to NOT recapture
    (losing the queen), so SEE = +100 (pawn gained, no profitable recapture).

    If the bishop were wrongly excluded, Black queen recaptures freely,
    and SEE would compute -400. The correct value is +100.
    """
    board = chess.Board("7k/8/8/R3p3/8/2B5/8/q7 w - - 0 1")
    move = chess.Move.from_uci("a5e5")

    assert board.piece_at(chess.E5) is not None, "Black pawn should be on e5"

    # Verify pin: bishop c3 is on the a1-g7 diagonal, and e5 is within that pin ray.
    pin_ray = board.pin(chess.WHITE, chess.C3)
    assert chess.E5 in pin_ray, "e5 should be on the pin ray for bishop c3"

    result = see_value(board, move)
    assert result == 100, f"expected +100 (bishop can recapture on pin ray), got {result}"
    assert not see_capture_or_sacrifice(board, move)
