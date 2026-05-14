"""
Title: test_stockfish_analyze_one_move.py — Tests for Stockfish PV-reuse fast path
Description:
    Verifies that local_worker.analysis.stockfish._analyze_one_move() skips
    the redundant second engine.analyse() call when the played move appears
    as the first move of one of the top-3 MultiPV lines (hit path), and
    falls back to a second call when it does not (miss path). Also asserts
    that on the hit path the post-move evaluation is sourced from the
    matching MultiPV entry's score (not from a poisoned after-call).

    Uses an in-process FakeEngine modelled on test_lc0_analyze_one_move.py
    so the suite needs no Stockfish binary at runtime.

Changelog:
    2026-05-13: Initial creation (issues #67/#61)
"""
from __future__ import annotations

from typing import Any

import chess
import chess.engine

from local_worker.analysis._stockfish_helpers import white_cp
from local_worker.analysis.stockfish import _analyze_one_move


class _FakeEngine:
    """Minimal stand-in for chess.engine.SimpleEngine used by stockfish tests.

    Records each ``analyse()`` invocation so tests can assert the exact call
    count and the per-call kwargs (notably ``multipv``). Returns a canned
    MultiPV result for ``multipv``-keyed calls and a canned single-PV info
    dict for the post-push call.
    """

    def __init__(
        self,
        multipv_result: list[dict[str, Any]],
        after_result: dict[str, Any],
    ) -> None:
        """Store canned engine outputs.

        Args:
            multipv_result: Returned from analyse(..., multipv=N) calls.
            after_result: Returned from analyse(...) calls without multipv.
        """
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
        """Record the call and return the matching canned result."""
        self.calls.append({"fen": board.fen(), "multipv": multipv})
        if multipv is not None:
            return self._multipv_result
        return self._after_result


def _povscore(white_cp_value: int) -> chess.engine.PovScore:
    """Build a real PovScore from a White-frame cp value.

    Args:
        white_cp_value: Centipawn evaluation in White's frame.

    Returns:
        A genuine ``chess.engine.PovScore`` so all downstream conversions
        (``.pov(color).score(...)``, mate handling) behave exactly like a
        live Stockfish result.
    """
    return chess.engine.PovScore(chess.engine.Cp(white_cp_value), chess.WHITE)


def _starting_board_and_move() -> tuple[chess.Board, chess.Move]:
    """Return the starting position and 1.e4 as a convenient test fixture."""
    return chess.Board(), chess.Move.from_uci("e2e4")


def test_hit_path_calls_analyse_once_when_move_in_top3_pv() -> None:
    """When the played move heads any top-3 PV, only the multipv call runs."""
    board, move = _starting_board_and_move()

    multipv_result = [
        {"score": _povscore(30), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _povscore(25), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _povscore(20), "pv": [chess.Move.from_uci("g1f3")]},
    ]
    after_result = {"score": _povscore(0)}

    engine = _FakeEngine(multipv_result, after_result)
    limit = chess.engine.Limit(depth=10)

    move_result, _move_acc, _wp_before, _cpl, _wp_after = _analyze_one_move(
        board, move, chess.WHITE, engine, limit,
    )

    assert len(engine.calls) == 1
    assert engine.calls[0]["multipv"] == 3
    assert move_result.san == "e4"


def test_miss_path_calls_analyse_twice_when_move_not_in_top3_pv() -> None:
    """When the played move is outside the top-3, a 2nd analyse() is issued."""
    board, move = _starting_board_and_move()

    multipv_result = [
        {"score": _povscore(40), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _povscore(30), "pv": [chess.Move.from_uci("g1f3")]},
        {"score": _povscore(25), "pv": [chess.Move.from_uci("c2c4")]},
    ]
    after_result = {"score": _povscore(-50)}

    engine = _FakeEngine(multipv_result, after_result)
    limit = chess.engine.Limit(depth=10)

    move_result, _move_acc, _wp_before, _cpl, _wp_after = _analyze_one_move(
        board, move, chess.WHITE, engine, limit,
    )

    assert len(engine.calls) == 2
    assert engine.calls[0]["multipv"] == 3
    assert engine.calls[1]["multipv"] is None
    # Post-move cp_eval must come from the dedicated after-call on the miss path.
    assert move_result.cp_eval == -50


def test_hit_path_score_source_is_matched_pv_entry() -> None:
    """On hit, eval_after_white must equal white_cp(matched PV's score).

    The fake's ``after_result`` is intentionally poisoned so that any
    accidental call would taint cp_eval. The assertion proves the score is
    sourced from ``info_before[matched_idx]['score']`` instead.
    """
    board, move = _starting_board_and_move()

    matched_score = _povscore(123)
    multipv_result = [
        {"score": _povscore(200), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": matched_score, "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _povscore(50), "pv": [chess.Move.from_uci("g1f3")]},
    ]
    poisoned_after = {"score": _povscore(-9999)}

    engine = _FakeEngine(multipv_result, poisoned_after)
    limit = chess.engine.Limit(depth=10)

    move_result, _move_acc, _wp_before, _cpl, _wp_after = _analyze_one_move(
        board, move, chess.WHITE, engine, limit,
    )

    assert len(engine.calls) == 1
    assert move_result.cp_eval == white_cp(matched_score)
