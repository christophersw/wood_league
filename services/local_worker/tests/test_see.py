"""
Title: test_see.py — Tests for Static Exchange Evaluation
Description:
    Verifies that see_capture_or_sacrifice() returns True only when the
    full exchange sequence on the destination square is a net material
    loss for the mover.

Changelog:
    2026-05-09: Initial creation
"""
import chess
import pytest
from local_worker.analysis.see import see_value, see_capture_or_sacrifice


def test_unprotected_pawn_capture_is_winning():
    # White pawn on e4 captures undefended pawn on d5 — SEE = +pawn
    board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    move = chess.Move.from_uci("e4d5")
    assert see_value(board, move) > 0
    assert not see_capture_or_sacrifice(board, move)


def test_queen_takes_defended_pawn_is_sacrifice():
    # White queen takes pawn on h7 defended by king — SEE strongly negative
    board = chess.Board("rnbqk2r/pppp1ppp/5n2/2b1p3/2B1P3/3P1N2/PPP2PPP/RNBQK2R w KQkq - 0 1")
    # Construct a clean test: White queen on h5 takes h7 defended by king
    board2 = chess.Board("4k2r/7p/8/7Q/8/8/8/4K3 w k - 0 1")
    move = chess.Move.from_uci("h5h7")
    assert see_value(board2, move) < 0
    assert see_capture_or_sacrifice(board2, move)


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
