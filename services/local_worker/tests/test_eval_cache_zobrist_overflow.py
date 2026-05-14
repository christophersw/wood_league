"""
Title: test_eval_cache_zobrist_overflow.py — Regression tests for issue #77
Description:
    Polyglot zobrist hashes are 64-bit unsigned. SQLite's INTEGER affinity
    is signed 64-bit; Python's sqlite3 driver raises OverflowError when bound
    a value >= 2**63. This test pins the wrap behaviour so we don't regress.

Changelog:
    2026-05-13: Initial creation (issue #77).
"""
from __future__ import annotations

from pathlib import Path

import chess
import chess.engine
import pytest

from local_worker.analysis.eval_cache import (
    CachedPv,
    EvalCache,
    _to_signed64,
)


_OVERFLOWING_ZOBRIST = 9443689642921087454  # > 2**63 - 1; from real worker crash
_FITTING_ZOBRIST = 12345678901234  # well under 2**63


def _make_entry() -> CachedPv:
    """Build a minimal CachedPv suitable for round-trip tests."""
    return CachedPv(
        wdl_white=chess.engine.Wdl(wins=400, draws=400, losses=200),
        pv_uci=["e2e4", "e7e5"],
    )


def test_to_signed64_high_bit_wraps() -> None:
    """A value with the 64th bit set wraps into the negative signed range."""
    signed = _to_signed64(_OVERFLOWING_ZOBRIST)
    assert signed < 0
    # Round-trip: applying the inverse (add 2**64 when negative) recovers it.
    assert (signed + (1 << 64)) == _OVERFLOWING_ZOBRIST


def test_to_signed64_no_op_for_low_values() -> None:
    """Values below 2**63 are unchanged."""
    assert _to_signed64(_FITTING_ZOBRIST) == _FITTING_ZOBRIST
    assert _to_signed64(0) == 0
    assert _to_signed64((1 << 63) - 1) == (1 << 63) - 1


def test_put_then_get_roundtrips_overflowing_zobrist(tmp_path: Path) -> None:
    """An overflowing zobrist must be storable and retrievable without raising."""
    cache = EvalCache(tmp_path / "eval_cache.sqlite")
    entry = _make_entry()
    cache.put(_OVERFLOWING_ZOBRIST, "lc0:test", 10000, 3, [entry])
    got = cache.get(_OVERFLOWING_ZOBRIST, "lc0:test", 10000, 3)
    cache.close()
    assert got is not None
    assert len(got) == 1
    assert got[0].pv_uci == ["e2e4", "e7e5"]


def test_overflow_and_fitting_keys_do_not_collide(tmp_path: Path) -> None:
    """Two distinct zobrist values produce two distinct entries even at the
    boundary where wrapping happens."""
    cache = EvalCache(tmp_path / "eval_cache.sqlite")
    entry_a = _make_entry()
    entry_b = CachedPv(
        wdl_white=chess.engine.Wdl(wins=100, draws=100, losses=800),
        pv_uci=["d2d4"],
    )
    cache.put(_OVERFLOWING_ZOBRIST, "lc0:test", 10000, 3, [entry_a])
    cache.put(_FITTING_ZOBRIST, "lc0:test", 10000, 3, [entry_b])
    got_a = cache.get(_OVERFLOWING_ZOBRIST, "lc0:test", 10000, 3)
    got_b = cache.get(_FITTING_ZOBRIST, "lc0:test", 10000, 3)
    cache.close()
    assert got_a is not None and got_a[0].pv_uci == ["e2e4", "e7e5"]
    assert got_b is not None and got_b[0].pv_uci == ["d2d4"]


def test_put_overflowing_zobrist_does_not_raise(tmp_path: Path) -> None:
    """Pre-fix, this raised OverflowError from the sqlite3 binding layer."""
    cache = EvalCache(tmp_path / "eval_cache.sqlite")
    try:
        cache.put(_OVERFLOWING_ZOBRIST, "sf:Stockfish 18", 20, 3, [_make_entry()])
    except OverflowError as exc:  # pragma: no cover - regression guard
        cache.close()
        pytest.fail(f"put() must not raise OverflowError on unsigned-64 zobrist: {exc}")
    cache.close()
