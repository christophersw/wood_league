"""
Title: test_lc0_analyze_one_move.py — Tests for _analyze_one_move PV-reuse fast path
Description:
    Verifies that _analyze_one_move() skips the redundant second engine.analyse()
    call when the played move appears as the first move of one of the top-3
    MultiPV lines (hit path), and falls back to a second call when it does not
    (miss path). Uses an in-process fake engine — no lc0 binary required.

Changelog:
    2026-05-13: Initial creation (issue #61)
"""
from __future__ import annotations

from typing import Any

import chess
import chess.engine

from local_worker.analysis.lc0 import _analyze_one_move


class _FakeEngine:
    """Minimal stand-in for chess.engine.SimpleEngine.

    Records each analyse() call so tests can assert the call count and the
    arguments used. Returns canned info dicts.
    """

    def __init__(self, multipv_result: list[dict[str, Any]], after_result: dict[str, Any]):
        self._multipv_result = multipv_result
        self._after_result = after_result
        self.calls: list[dict[str, Any]] = []

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        self.calls.append({"fen": board.fen(), "multipv": multipv})
        if multipv is not None:
            return self._multipv_result
        return self._after_result


class _RelScore:
    """Relative score stand-in: returns a fixed Wdl from .wdl()."""

    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_args: object, **_kwargs: object) -> chess.engine.Wdl:
        return self._wdl


class _FakePovScore:
    """PovScore stand-in: .pov(color) flips wins/losses for the non-White side."""

    def __init__(self, wins: int, draws: int, losses: int) -> None:
        self._white = chess.engine.Wdl(wins=wins, draws=draws, losses=losses)
        self._black = chess.engine.Wdl(wins=losses, draws=draws, losses=wins)

    def pov(self, color: chess.Color) -> _RelScore:
        return _RelScore(self._white if color == chess.WHITE else self._black)


def _score(win: int, draw: int, loss: int) -> _FakePovScore:
    """Build a fake PovScore from raw WDL permille values, in White's frame."""
    return _FakePovScore(win, draw, loss)


def _starting_board_and_move() -> tuple[chess.Board, chess.Move]:
    board = chess.Board()
    move = chess.Move.from_uci("e2e4")
    return board, move


def test_hit_path_calls_analyse_once_when_move_in_top3_pv():
    """When the played move is the top PV, only one analyse() call is made."""
    board, move = _starting_board_and_move()

    multipv_result = [
        {"score": _score(500, 400, 100), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _score(480, 400, 120), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _score(460, 400, 140), "pv": [chess.Move.from_uci("g1f3")]},
    ]
    after_result = {"score": _score(0, 0, 0)}

    engine = _FakeEngine(multipv_result, after_result)
    limit = chess.engine.Limit(nodes=1000)

    result, mover, _wdl_white = _analyze_one_move(board, move, 1, engine, limit)

    assert len(engine.calls) == 1
    assert engine.calls[0]["multipv"] == 3
    assert result.ply == 1
    assert result.san == "e4"
    assert mover == chess.WHITE


def test_hit_path_score_matches_matching_pv_entry():
    """The cp_equiv/wdl come from the matching PV entry, not the after-call."""
    board, move = _starting_board_and_move()

    multipv_result = [
        {"score": _score(480, 400, 120), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _score(500, 400, 100), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _score(460, 400, 140), "pv": [chess.Move.from_uci("g1f3")]},
    ]
    poisoned_after = {"score": _score(0, 0, 1000)}

    engine = _FakeEngine(multipv_result, poisoned_after)
    limit = chess.engine.Limit(nodes=1000)

    result, _mover, wdl_white = _analyze_one_move(board, move, 1, engine, limit)

    assert len(engine.calls) == 1
    assert wdl_white == (500, 400, 100)
    assert result.wdl_win == 500 and result.wdl_loss == 100


def test_miss_path_falls_back_to_second_analyse_when_move_not_in_pv():
    """When played move is outside top-3 PV, a second analyse() runs."""
    board, move = _starting_board_and_move()

    multipv_result = [
        {"score": _score(500, 400, 100), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _score(480, 400, 120), "pv": [chess.Move.from_uci("g1f3")]},
        {"score": _score(460, 400, 140), "pv": [chess.Move.from_uci("c2c4")]},
    ]
    after_result = {"score": _score(450, 400, 150)}

    engine = _FakeEngine(multipv_result, after_result)
    limit = chess.engine.Limit(nodes=1000)

    result, _mover, wdl_white = _analyze_one_move(board, move, 1, engine, limit)

    assert len(engine.calls) == 2
    assert engine.calls[0]["multipv"] == 3
    assert engine.calls[1]["multipv"] is None
    assert wdl_white == (450, 400, 150)
    assert result.wdl_win == 450
