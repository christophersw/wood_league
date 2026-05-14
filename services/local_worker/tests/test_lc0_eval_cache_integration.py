"""
Title: test_lc0_eval_cache_integration.py — In-process tests for cache wiring
Description:
    Verifies that _analyze_one_move() consults the eval cache before calling
    the engine and writes back on miss. Uses the FakeEngine pattern from
    test_lc0_analyze_one_move.py — no real lc0 binary required.

Changelog:
    2026-05-13: Initial creation (issue #65)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chess
import chess.engine

from local_worker.analysis.eval_cache import (
    CachedPv,
    EvalCache,
    zobrist_key,
)
from local_worker.analysis.lc0 import _analyze_one_move


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
        return self._multipv_result if multipv is not None else self._after_result


def _starting() -> tuple[chess.Board, chess.Move]:
    return chess.Board(), chess.Move.from_uci("e2e4")


def _multipv_payload() -> list[dict[str, Any]]:
    return [
        {"score": _PovScore(500, 400, 100), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _PovScore(480, 400, 120), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _PovScore(460, 400, 140), "pv": [chess.Move.from_uci("g1f3")]},
    ]


def test_first_call_misses_then_writes_back(tmp_path: Path) -> None:
    board, move = _starting()
    engine = _FakeEngine(_multipv_payload(), {"score": _PovScore(0, 0, 0)})
    cache = EvalCache(tmp_path / "cache.sqlite")

    _analyze_one_move(
        board, move, 1, engine, chess.engine.Limit(nodes=1000),
        cache=cache, network="BT4", nodes=25000,
    )

    assert engine.calls and engine.calls[0]["multipv"] == 3
    assert cache.stats().hits == 0
    # The cache is consulted before the engine call; an absent key is a miss.
    assert cache.stats().misses == 1
    # And the engine result is written back.
    assert cache.get(zobrist_key(chess.Board()), "BT4", 25000, 3) is not None
    cache.close()


def test_second_call_hits_and_skips_engine(tmp_path: Path) -> None:
    """Second analysis of the same position should hit the cache and not call analyse(multipv)."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    # Pre-warm cache.
    cache.put(
        zobrist_key(chess.Board()), "BT4", 25000, 3,
        [
            CachedPv(wdl_white=chess.engine.Wdl(500, 400, 100), pv_uci=["e2e4"]),
            CachedPv(wdl_white=chess.engine.Wdl(480, 400, 120), pv_uci=["d2d4"]),
            CachedPv(wdl_white=chess.engine.Wdl(460, 400, 140), pv_uci=["g1f3"]),
        ],
    )

    board, move = _starting()
    engine = _FakeEngine(_multipv_payload(), {"score": _PovScore(0, 0, 0)})

    result, _mover, wdl_white = _analyze_one_move(
        board, move, 1, engine, chess.engine.Limit(nodes=1000),
        cache=cache, network="BT4", nodes=25000,
    )

    multipv_calls = [c for c in engine.calls if c["multipv"] == 3]
    assert multipv_calls == []  # cache hit ⇒ no live engine call for multipv
    assert wdl_white == (500, 400, 100)
    assert result.wdl_win == 500
    cache.close()


def test_empty_network_bypasses_cache(tmp_path: Path) -> None:
    """When network is empty, cache is not consulted nor written."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    board, move = _starting()
    engine = _FakeEngine(_multipv_payload(), {"score": _PovScore(0, 0, 0)})

    _analyze_one_move(
        board, move, 1, engine, chess.engine.Limit(nodes=1000),
        cache=cache, network="", nodes=25000,
    )

    assert cache.stats().rows == 0
    cache.close()


def test_disabled_cache_falls_through_to_engine(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite", enabled=False)
    board, move = _starting()
    engine = _FakeEngine(_multipv_payload(), {"score": _PovScore(0, 0, 0)})

    _analyze_one_move(
        board, move, 1, engine, chess.engine.Limit(nodes=1000),
        cache=cache, network="BT4", nodes=25000,
    )

    assert any(c["multipv"] == 3 for c in engine.calls)
    cache.close()
