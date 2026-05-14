"""
Title: test_lc0_terminal_handling.py — Tests for terminal-position handling (#58)
Description:
    Regression coverage for the crash where lc0 emits ``bestmove a1a1``
    when asked to search a terminal position (checkmate / stalemate /
    insufficient material), which python-chess parses as an invalid UCI
    and kills the engine event loop. `_analyze_one_move` now short-circuits
    the post-move engine call on terminal boards, supplying a synthesised
    deterministic score.

    Uses an in-process fake engine so no lc0 binary is required.

Changelog:
    2026-05-13: Initial creation (issue #58)
"""
from __future__ import annotations

from typing import Any

import chess
import chess.engine

from local_worker.analysis.lc0 import (
    _TerminalPovScore,
    _analyze_one_move,
    _multipv_before,
    _terminal_info_list,
    _terminal_wdl_white,
)


class _RelScore:
    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_a: object, **_k: object) -> chess.engine.Wdl:
        return self._wdl


class _PovScore:
    def __init__(self, wins: int, draws: int, losses: int) -> None:
        self._white = chess.engine.Wdl(wins=wins, draws=draws, losses=losses)
        self._black = chess.engine.Wdl(wins=losses, draws=draws, losses=wins)

    def pov(self, color: chess.Color) -> _RelScore:
        return _RelScore(self._white if color == chess.WHITE else self._black)


class _FakeEngine:
    """Records every analyse() call. analyse() on a terminal board MUST NOT happen."""

    def __init__(self, multipv_result: list[dict[str, Any]] | None = None) -> None:
        self._multipv_result = multipv_result or []
        self.calls: list[dict[str, Any]] = []

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        self.calls.append({"fen": board.fen(), "multipv": multipv})
        return self._multipv_result if multipv is not None else {"score": _PovScore(0, 0, 0)}


# --- _terminal_wdl_white ----------------------------------------------------


def _board_after(moves_san: list[str]) -> chess.Board:
    board = chess.Board()
    for san in moves_san:
        board.push_san(san)
    return board


def test_terminal_wdl_checkmate_white_to_move_loses() -> None:
    """Fool's mate: White is mated → wdl_white = (0, 0, 1000)."""
    board = _board_after(["f3", "e5", "g4", "Qh4#"])
    assert board.is_checkmate() and board.turn == chess.WHITE
    assert _terminal_wdl_white(board) == (0, 0, 1000)


def test_terminal_wdl_checkmate_black_to_move_loses() -> None:
    """Scholar's mate: Black is mated → wdl_white = (1000, 0, 0)."""
    board = _board_after(["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"])
    assert board.is_checkmate() and board.turn == chess.BLACK
    assert _terminal_wdl_white(board) == (1000, 0, 0)


def test_terminal_wdl_stalemate_is_draw() -> None:
    """Stalemate (and other non-mate terminals) score as a draw."""
    # Construct a classic stalemate: White king h8, Black king f7, Black queen g6.
    board = chess.Board("7k/8/5KQ1/8/8/8/8/8 b - - 0 1")
    # Manually craft via FEN: White stalemates Black via Kf6 Qg6 with bK on h8.
    # Simpler: use a known stalemate FEN where it's White's move but White has no legal move.
    board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert board.is_stalemate()
    assert _terminal_wdl_white(board) == (0, 1000, 0)


# --- _TerminalPovScore -----------------------------------------------------


def test_terminal_pov_score_flips_for_black() -> None:
    score = _TerminalPovScore((1000, 0, 0))  # White wins
    assert score.pov(chess.WHITE).wdl() == chess.engine.Wdl(1000, 0, 0)
    assert score.pov(chess.BLACK).wdl() == chess.engine.Wdl(0, 0, 1000)


def test_terminal_info_list_has_one_entry_with_empty_pv() -> None:
    board = _board_after(["f3", "e5", "g4", "Qh4#"])
    info_list = _terminal_info_list(board)
    assert len(info_list) == 1
    assert info_list[0]["pv"] == []
    # White is mated; from mover (White) POV: loss.
    assert info_list[0]["score"].pov(chess.WHITE).wdl().losses == 1000


# --- _multipv_before short-circuit -----------------------------------------


def test_multipv_before_skips_engine_for_terminal_board() -> None:
    """Calling _multipv_before on a checkmate must not invoke engine.analyse."""
    board = _board_after(["f3", "e5", "g4", "Qh4#"])
    engine = _FakeEngine()
    info = _multipv_before(
        board, engine, chess.engine.Limit(nodes=1000),
        cache=None, network="", nodes=0, multipv=3,
    )
    assert engine.calls == []
    assert info[0]["pv"] == []


# --- _analyze_one_move full path -------------------------------------------


def test_analyze_one_move_skips_engine_when_played_move_mates() -> None:
    """The mating move pushes the board into checkmate; no after-call to engine."""
    board = _board_after(["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6"])
    move = chess.Move.from_uci("h5f7")  # Qxf7#

    # Top-3 PV result for the position BEFORE Qxf7#. We deliberately omit
    # the mating move so the hit-path doesn't shortcut and the miss-path
    # is exercised end-to-end.
    multipv = [
        {"score": _PovScore(900, 80, 20), "pv": [chess.Move.from_uci("c4f7")]},
        {"score": _PovScore(890, 80, 30), "pv": [chess.Move.from_uci("h5h7")]},
        {"score": _PovScore(880, 80, 40), "pv": [chess.Move.from_uci("h5e5")]},
    ]
    engine = _FakeEngine(multipv)

    result, mover, wdl_white = _analyze_one_move(
        board, move, 7, engine, chess.engine.Limit(nodes=1000),
        cache=None, network="", nodes=0,
    )

    # Only the multipv=3 "before" call ran — no second analyse() on the
    # terminal "after" position, which would have crashed on real lc0.
    after_calls = [c for c in engine.calls if c["multipv"] is None]
    assert after_calls == []
    assert mover == chess.WHITE
    # After Qxf7# it is Black to move and Black is mated → wdl_white wins.
    assert wdl_white == (1000, 0, 0)
    assert result.wdl_win == 1000


def test_analyze_one_move_normal_board_still_calls_engine_on_miss() -> None:
    """Sanity guard: non-terminal miss path still invokes the engine."""
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    # multipv doesn't contain e2e4 → miss path
    multipv = [
        {"score": _PovScore(500, 400, 100), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _PovScore(490, 400, 110), "pv": [chess.Move.from_uci("g1f3")]},
        {"score": _PovScore(480, 400, 120), "pv": [chess.Move.from_uci("c2c4")]},
    ]
    engine = _FakeEngine(multipv)

    _analyze_one_move(
        board, move, 1, engine, chess.engine.Limit(nodes=1000),
        cache=None, network="", nodes=0,
    )

    assert any(c["multipv"] is None for c in engine.calls)
