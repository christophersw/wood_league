"""
Title: test_eval_cache.py — Unit tests for the persistent lc0 eval cache
Description:
    Round-trip / key-sensitivity / transposition / LRU / corrupt-DB /
    info-list adapter tests for `local_worker.analysis.eval_cache`.
    All tests use temporary SQLite files via tmp_path — no real lc0.

Changelog:
    2026-05-13: Initial creation (issue #65)
"""
from __future__ import annotations

from pathlib import Path

import chess
import chess.engine
import chess.pgn
import pytest

from local_worker.analysis.eval_cache import (
    CachedPv,
    EvalCache,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
    zobrist_key,
)


def _wdl(wins: int, draws: int, losses: int) -> chess.engine.Wdl:
    return chess.engine.Wdl(wins=wins, draws=draws, losses=losses)


def _make_entries() -> list[CachedPv]:
    return [
        CachedPv(wdl_white=_wdl(500, 400, 100), pv_uci=["e2e4", "e7e5", "g1f3"]),
        CachedPv(wdl_white=_wdl(480, 400, 120), pv_uci=["d2d4", "d7d5"]),
        CachedPv(wdl_white=_wdl(460, 400, 140), pv_uci=[]),
    ]


def test_put_then_get_round_trips_entries(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(123, "BT4", 25000, 3, _make_entries())
    got = cache.get(123, "BT4", 25000, 3)
    assert got is not None
    assert [(e.wdl_white.wins, e.wdl_white.losses, e.pv_uci) for e in got] == [
        (500, 100, ["e2e4", "e7e5", "g1f3"]),
        (480, 120, ["d2d4", "d7d5"]),
        (460, 140, []),
    ]
    cache.close()


def test_get_miss_returns_none(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    assert cache.get(999, "BT4", 25000, 3) is None
    assert cache.stats().misses == 1
    cache.close()


def test_key_sensitivity_network_nodes_multipv(tmp_path: Path) -> None:
    """Different network / nodes / multipv must produce separate cache entries."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(42, "BT4", 25000, 3, _make_entries())
    assert cache.get(42, "T80", 25000, 3) is None     # different network
    assert cache.get(42, "BT4", 50000, 3) is None     # different nodes
    assert cache.get(42, "BT4", 25000, 1) is None     # different multipv
    assert cache.get(42, "BT4", 25000, 3) is not None
    cache.close()


def test_zobrist_transposition_same_key(tmp_path: Path) -> None:
    """Same position via different move orders → same zobrist key.

    Uses a 6-ply sequence where the last move is not a pawn double-push, so
    en-passant state is cleared and identical between the two orders.
    """
    board_a = chess.Board()
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"]:
        board_a.push(chess.Move.from_uci(uci))

    board_b = chess.Board()
    for uci in ["e2e4", "e7e5", "f1c4", "f8c5", "g1f3", "b8c6"]:
        board_b.push(chess.Move.from_uci(uci))

    assert board_a.fen() == board_b.fen()
    assert zobrist_key(board_a) == zobrist_key(board_b)


def test_disabled_cache_is_noop(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite", enabled=False)
    cache.put(1, "BT4", 25000, 3, _make_entries())
    assert cache.get(1, "BT4", 25000, 3) is None
    assert cache.stats().hits == 0 and cache.stats().misses == 0
    cache.close()


def test_clear_empties_all_rows(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    for zob in range(5):
        cache.put(zob, "BT4", 25000, 3, _make_entries())
    assert cache.stats().rows == 5
    cache.clear()
    assert cache.stats().rows == 0
    cache.close()


def test_hit_updates_last_used_for_lru(tmp_path: Path, monkeypatch) -> None:
    """get() must bump last_used_at so the row moves to the LRU tail.

    SQLite stores seconds-resolution timestamps, so two operations in the
    same second can't be ordered by last_used_at alone. Fake `time.time`
    to a monotonic counter for this test.
    """
    counter = iter(range(1000, 9999))

    def _fake_time() -> int:
        return next(counter)

    monkeypatch.setattr("local_worker.analysis.eval_cache.time.time", _fake_time)

    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(1, "BT4", 25000, 3, _make_entries())
    cache.put(2, "BT4", 25000, 3, _make_entries())
    cache.get(1, "BT4", 25000, 3)  # Touch row 1 → newest.

    assert cache._conn is not None
    cur = cache._conn.execute(
        "SELECT zobrist FROM eval_cache ORDER BY last_used_at ASC"
    )
    rows = [r[0] for r in cur.fetchall()]
    assert rows[0] == 2 and rows[-1] == 1
    cache.close()


def test_corrupt_payload_treated_as_miss(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    assert cache._conn is not None
    cache._conn.execute(
        "INSERT INTO eval_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "BT4", 25000, 3, "not-json", 0, 0),
    )
    cache._conn.commit()
    assert cache.get(1, "BT4", 25000, 3) is None
    cache.close()


def test_corrupt_db_recreates(tmp_path: Path) -> None:
    """A corrupt SQLite file is deleted and recreated, not propagated."""
    db_path = tmp_path / "cache.sqlite"
    db_path.write_bytes(b"this is not a valid sqlite database")
    cache = EvalCache(db_path)
    cache.put(1, "BT4", 25000, 3, _make_entries())
    assert cache.get(1, "BT4", 25000, 3) is not None
    cache.close()


def test_info_list_round_trip_via_cache_adapters(tmp_path: Path) -> None:
    """Live info-list shape survives put → get with .pov().wdl() intact."""
    entries = _make_entries()
    info_list = cached_pvs_to_info_list(entries)
    assert info_list[0]["pv"][0].uci() == "e2e4"
    assert info_list[0]["score"].pov(chess.WHITE).wdl() == _wdl(500, 400, 100)
    assert info_list[0]["score"].pov(chess.BLACK).wdl() == _wdl(100, 400, 500)


def test_info_list_to_cached_pvs_uses_white_frame(tmp_path: Path) -> None:
    """info_list_to_cached_pvs() stores WDL in White's frame regardless of mover."""
    info_list = cached_pvs_to_info_list(_make_entries())
    encoded = info_list_to_cached_pvs(info_list)
    assert encoded[0].wdl_white == _wdl(500, 400, 100)
    assert encoded[0].pv_uci == ["e2e4", "e7e5", "g1f3"]


def test_info_list_to_cached_pvs_truncates_long_pvs(tmp_path: Path) -> None:
    long_entry = CachedPv(
        wdl_white=_wdl(500, 400, 100),
        pv_uci=[f"e{i % 8 + 1}e{(i + 1) % 8 + 1}" for i in range(20)],
    )
    info_list = cached_pvs_to_info_list([long_entry])
    encoded = info_list_to_cached_pvs(info_list, max_pv_plies=5)
    assert len(encoded[0].pv_uci) == 5


def test_reset_counters(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(1, "BT4", 25000, 3, _make_entries())
    cache.get(1, "BT4", 25000, 3)
    cache.get(2, "BT4", 25000, 3)
    assert cache.stats().hits == 1 and cache.stats().misses == 1
    cache.reset_counters()
    assert cache.stats().hits == 0 and cache.stats().misses == 0
    cache.close()


def test_stats_size_bytes_tracks_file(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    for zob in range(20):
        cache.put(zob, "BT4", 25000, 3, _make_entries())
    assert cache.stats().size_bytes > 0
    assert cache.stats().rows == 20
    cache.close()


def test_empty_network_disables_keying(tmp_path: Path) -> None:
    """Caller passing empty network is the contract for 'no cache'."""
    # This is enforced upstream in lc0.py; here we just confirm the cache
    # itself permits the empty key and round-trips it, so the upstream
    # guard is the only line of defence and we don't accidentally key on
    # the empty string and produce collisions.
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(1, "", 25000, 3, _make_entries())
    cache.put(1, "BT4", 25000, 3, _make_entries())
    assert cache.get(1, "", 25000, 3) is not None
    assert cache.get(1, "BT4", 25000, 3) is not None
    cache.close()


def test_prune_evicts_under_target(tmp_path: Path) -> None:
    """prune() returns the number of rows deleted when file exceeds max."""
    cache = EvalCache(tmp_path / "cache.sqlite")
    big_entries = [
        CachedPv(wdl_white=_wdl(500, 400, 100), pv_uci=["e2e4"] * 50)
        for _ in range(3)
    ]
    for zob in range(200):
        cache.put(zob, "BT4", 25000, 3, big_entries)
    size_before = cache.stats().size_bytes
    assert size_before > 0
    deleted = cache.prune(max_bytes=size_before // 2, target_bytes=size_before // 4)
    assert deleted > 0
    assert cache.stats().rows < 200
    cache.close()


def test_prune_noop_when_under_threshold(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(1, "BT4", 25000, 3, _make_entries())
    assert cache.prune(max_bytes=10_000_000) == 0
    assert cache.stats().rows == 1
    cache.close()


def test_overwrite_existing_entry(tmp_path: Path) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    cache.put(1, "BT4", 25000, 3, _make_entries())
    new_entries = [CachedPv(wdl_white=_wdl(900, 50, 50), pv_uci=["a2a4"])]
    cache.put(1, "BT4", 25000, 3, new_entries)
    got = cache.get(1, "BT4", 25000, 3)
    assert got is not None and got[0].wdl_white.wins == 900
    assert cache.stats().rows == 1
    cache.close()


@pytest.mark.parametrize("schema_version_overwrite", [0, 999])
def test_unknown_schema_treated_as_miss(
    tmp_path: Path, schema_version_overwrite: int
) -> None:
    cache = EvalCache(tmp_path / "cache.sqlite")
    assert cache._conn is not None
    cache._conn.execute(
        "INSERT INTO eval_cache VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "BT4", 25000, 3,
         '{"v": ' + str(schema_version_overwrite) + ', "pvs": []}',
         0, 0),
    )
    cache._conn.commit()
    assert cache.get(1, "BT4", 25000, 3) is None
    cache.close()
