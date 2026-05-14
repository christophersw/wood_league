"""
Title: test_eval_cache_sf.py — Stockfish-side tests for the persistent eval cache
Description:
    Round-trip / key-sensitivity / cross-engine isolation / schema-v1 /
    Stockfish multipv_before integration tests for the SF read+write path
    added in issue #67. Uses temporary SQLite files via tmp_path and the
    same FakeEngine pattern as test_stockfish_analyze_one_move.py — no
    real Stockfish binary required.

Changelog:
    2026-05-13: Initial creation (issue #67, builds on #65)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chess
import chess.engine

from local_worker.analysis._stockfish_helpers import white_cp
from local_worker.analysis.eval_cache import (
    CachedPv,
    EvalCache,
    SCHEMA_VERSION,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
    zobrist_key,
)
from local_worker.analysis.math import MATE_SCORE
from local_worker.analysis.stockfish import _multipv_before_sf


# --- helpers -----------------------------------------------------------


class _FakeEngine:
    """Minimal stand-in matching the SF MultiPV helper's expected surface."""

    def __init__(self, multipv_result: list[dict[str, Any]]) -> None:
        """Store canned engine outputs.

        Args:
            multipv_result: Returned from analyse(..., multipv=N) calls.
        """
        self._multipv_result = multipv_result
        self.calls: list[dict[str, Any]] = []

    def analyse(
        self,
        board: chess.Board,
        limit: chess.engine.Limit,
        *,
        multipv: int | None = None,
    ) -> Any:
        """Record the call and return the canned multipv result."""
        self.calls.append({"fen": board.fen(), "multipv": multipv})
        return self._multipv_result


def _povscore_cp(white_cp_value: int) -> chess.engine.PovScore:
    """Build a real PovScore from a White-frame cp value."""
    return chess.engine.PovScore(chess.engine.Cp(white_cp_value), chess.WHITE)


def _povscore_mate(white_mate_plies: int) -> chess.engine.PovScore:
    """Build a real PovScore from a White-frame mate distance.

    Args:
        white_mate_plies: Positive = White mates in N plies, negative =
            Black mates in N plies.

    Returns:
        Real chess.engine.PovScore with Mate(plies) as the relative score
        from White's POV.
    """
    return chess.engine.PovScore(chess.engine.Mate(white_mate_plies), chess.WHITE)


def _multipv_payload_cp() -> list[dict[str, Any]]:
    return [
        {"score": _povscore_cp(50), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _povscore_cp(30), "pv": [chess.Move.from_uci("d2d4")]},
        {"score": _povscore_cp(15), "pv": [chess.Move.from_uci("g1f3")]},
    ]


# --- core round-trip ---------------------------------------------------


def test_stockfish_round_trip_cp(tmp_path: Path) -> None:
    """Put cp+mate via the SF adapters; get back identical PovScore semantics."""
    info_list = _multipv_payload_cp()
    cached = info_list_to_cached_pvs(info_list, engine="stockfish")
    assert cached[0].cp_white == 50
    assert cached[0].mate_white is None

    rebuilt = cached_pvs_to_info_list(cached, engine="stockfish")
    # cp from White's frame survives.
    assert white_cp(rebuilt[0]["score"]) == 50
    # And from Black's frame it correctly negates.
    assert rebuilt[0]["score"].pov(chess.BLACK).score(mate_score=MATE_SCORE) == -50


def test_stockfish_round_trip_mate(tmp_path: Path) -> None:
    """Mate distance round-trips via the cache encoding."""
    info_list = [
        {"score": _povscore_mate(3), "pv": [chess.Move.from_uci("e2e4")]},
        {"score": _povscore_mate(-5), "pv": [chess.Move.from_uci("d2d4")]},
    ]
    cached = info_list_to_cached_pvs(info_list, engine="stockfish")
    assert cached[0].mate_white == 3
    assert cached[1].mate_white == -5

    rebuilt = cached_pvs_to_info_list(cached, engine="stockfish")
    # White mates in 3 → from White's POV, Mate(3); from Black's, Mate(-3).
    assert rebuilt[0]["score"].pov(chess.WHITE).mate() == 3
    assert rebuilt[0]["score"].pov(chess.BLACK).mate() == -3
    # Black mates in 5 → from White's POV, Mate(-5).
    assert rebuilt[1]["score"].pov(chess.WHITE).mate() == -5
    assert rebuilt[1]["score"].pov(chess.BLACK).mate() == 5


def test_stockfish_persisted_round_trip_via_sqlite(tmp_path: Path) -> None:
    """Real put → get cycle through the SQLite layer preserves cp + mate."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    entries = info_list_to_cached_pvs(
        [
            {"score": _povscore_cp(120), "pv": [chess.Move.from_uci("e2e4")]},
            {"score": _povscore_mate(2), "pv": [chess.Move.from_uci("h2h4")]},
        ],
        engine="stockfish",
    )
    cache.put(99, "sf:Stockfish 16", 20, 3, entries)
    got = cache.get(99, "sf:Stockfish 16", 20, 3)
    assert got is not None
    assert got[0].cp_white == 120
    assert got[1].mate_white == 2
    cache.close()


# --- key sensitivity ---------------------------------------------------


def test_stockfish_depth_keys_separately(tmp_path: Path) -> None:
    """Different depth (passed via the `nodes` column) → separate entries."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    entries = [CachedPv(
        wdl_white=chess.engine.Wdl(0, 1000, 0),
        pv_uci=["e2e4"],
        cp_white=10,
    )]
    cache.put(7, "sf:Stockfish 16", 20, 3, entries)
    assert cache.get(7, "sf:Stockfish 16", 25, 3) is None
    assert cache.get(7, "sf:Stockfish 16", 20, 3) is not None
    cache.close()


def test_stockfish_engine_id_keys_separately(tmp_path: Path) -> None:
    """Different engine_id (network prefix) → separate entries."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    entries = [CachedPv(
        wdl_white=chess.engine.Wdl(0, 1000, 0),
        pv_uci=["e2e4"],
        cp_white=10,
    )]
    cache.put(7, "sf:Stockfish 16", 20, 3, entries)
    assert cache.get(7, "sf:Stockfish 17", 20, 3) is None
    assert cache.get(7, "sf:Stockfish 16", 20, 3) is not None
    cache.close()


def test_cross_engine_isolation_lc0_vs_sf(tmp_path: Path) -> None:
    """An lc0 entry at the same Zobrist must not collide with an SF entry."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    lc0_entry = [CachedPv(
        wdl_white=chess.engine.Wdl(500, 400, 100),
        pv_uci=["e2e4"],
    )]
    sf_entry = [CachedPv(
        wdl_white=chess.engine.Wdl(0, 1000, 0),
        pv_uci=["d2d4"],
        cp_white=42,
    )]
    cache.put(123, "BT4", 25000, 3, lc0_entry)
    cache.put(123, "sf:Stockfish 16", 20, 3, sf_entry)

    lc0_got = cache.get(123, "BT4", 25000, 3)
    sf_got = cache.get(123, "sf:Stockfish 16", 20, 3)
    assert lc0_got is not None and lc0_got[0].pv_uci == ["e2e4"]
    assert sf_got is not None and sf_got[0].cp_white == 42
    cache.close()


# --- schema v1 backwards-incompatibility ------------------------------


def test_schema_v1_treated_as_miss(tmp_path: Path) -> None:
    """A row written under SCHEMA_VERSION=1 is a miss, not a crash."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    assert cache._conn is not None
    legacy_payload = (
        '{"v": 1, "pvs": [{"w": 500, "d": 400, "l": 100, "pv": ["e2e4"]}]}'
    )
    cache._conn.execute(
        "INSERT INTO eval_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "BT4", 25000, 3, legacy_payload, 0, 0),
    )
    cache._conn.commit()
    assert cache.get(1, "BT4", 25000, 3) is None
    cache.close()


def test_current_schema_version_is_two() -> None:
    """Guard rail so the v1 → v2 bump doesn't silently regress."""
    assert SCHEMA_VERSION == 2


# --- _multipv_before_sf integration -----------------------------------


def test_sf_multipv_before_miss_calls_engine_and_writes(tmp_path: Path) -> None:
    """Cold cache: engine.analyse runs and the result is persisted."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    engine = _FakeEngine(_multipv_payload_cp())
    board = chess.Board()

    info = _multipv_before_sf(
        board, engine, chess.engine.Limit(depth=20),
        cache=cache, network="sf:Stockfish 16", nodes=20, multipv=3,
    )

    assert len(engine.calls) == 1
    assert engine.calls[0]["multipv"] == 3
    assert white_cp(info[0]["score"]) == 50
    # And it was written back.
    got = cache.get(zobrist_key(board), "sf:Stockfish 16", 20, 3)
    assert got is not None and got[0].cp_white == 50
    cache.close()


def test_sf_multipv_before_hit_skips_engine(tmp_path: Path) -> None:
    """Warm cache: engine.analyse is never called and the score round-trips."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    board = chess.Board()
    cache.put(
        zobrist_key(board), "sf:Stockfish 16", 20, 3,
        info_list_to_cached_pvs(_multipv_payload_cp(), engine="stockfish"),
    )

    engine = _FakeEngine([])  # Would explode if called.
    info = _multipv_before_sf(
        board, engine, chess.engine.Limit(depth=20),
        cache=cache, network="sf:Stockfish 16", nodes=20, multipv=3,
    )

    assert engine.calls == []
    assert white_cp(info[0]["score"]) == 50
    # PV move survives so arrow extraction continues to work.
    assert info[0]["pv"][0].uci() == "e2e4"
    cache.close()


def test_sf_multipv_before_empty_network_bypasses_cache(tmp_path: Path) -> None:
    """Empty network key is the contract for 'no cache'."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    engine = _FakeEngine(_multipv_payload_cp())
    board = chess.Board()

    _multipv_before_sf(
        board, engine, chess.engine.Limit(depth=20),
        cache=cache, network="", nodes=20, multipv=3,
    )

    assert len(engine.calls) == 1
    assert cache.stats().rows == 0
    cache.close()


def test_sf_multipv_before_disabled_cache_falls_through(tmp_path: Path) -> None:
    """Disabled cache must still let the engine call through."""
    cache = EvalCache(tmp_path / "cache.sqlite", enabled=False)
    engine = _FakeEngine(_multipv_payload_cp())
    board = chess.Board()

    _multipv_before_sf(
        board, engine, chess.engine.Limit(depth=20),
        cache=cache, network="sf:Stockfish 16", nodes=20, multipv=3,
    )

    assert len(engine.calls) == 1
    cache.close()
