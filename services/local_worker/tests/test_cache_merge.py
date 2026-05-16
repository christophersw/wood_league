"""
Title: test_cache_merge.py — tests for the offline eval-cache delta merge
Description:
    Tests for ``cache_merge.merge_deltas`` — union of per-instance delta
    caches into the canonical (INSERT OR REPLACE last-writer-wins),
    prune to the size cap, vacuum.
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
import sqlite3
from pathlib import Path

from local_worker.analysis.eval_cache import EvalCache
from local_worker.cache_merge import merge_deltas


def _seed(path: Path, rows):
    """rows: list of (zobrist, network, nodes, multipv, payload, ts)."""
    cache = EvalCache(path)  # creates schema (table eval_cache)
    cache.close()
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT OR REPLACE INTO eval_cache "
        "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [(z, n, nd, m, p, ts, ts) for (z, n, nd, m, p, ts) in rows],
    )
    conn.commit()
    conn.close()


def test_merge_unions_and_last_writer_wins(tmp_path):
    canonical = tmp_path / "canonical.sqlite"
    d1 = tmp_path / "d1.sqlite"
    d2 = tmp_path / "d2.sqlite"
    _seed(canonical, [(1, "BT4", 100, 3, '{"v":2,"pvs":[]}', 10)])
    _seed(d1, [(2, "BT4", 100, 3, '{"v":2,"pvs":[]}', 20)])
    # same PK as canonical row 1, newer ts -> should win
    _seed(d2, [(1, "BT4", 100, 3, '{"v":2,"pvs":[{"w":1}]}', 99)])

    merged = merge_deltas(canonical, [d1, d2], max_bytes=50 * 1024 * 1024)

    conn = sqlite3.connect(canonical)
    rows = dict(
        (z, payload)
        for (z, payload) in conn.execute(
            "SELECT zobrist, payload FROM eval_cache"
        ).fetchall()
    )
    conn.close()
    assert set(rows) == {1, 2}                       # union
    assert rows[1] == '{"v":2,"pvs":[{"w":1}]}'      # last-writer-wins
    assert merged == 2                               # rows in canonical


def test_merge_copies_rows_verbatim_including_legacy(tmp_path):
    """v1 payloads are copied raw; readers already treat v1 as a miss."""
    canonical = tmp_path / "canonical.sqlite"
    d1 = tmp_path / "d1.sqlite"
    _seed(canonical, [])
    _seed(d1, [(7, "BT4", 100, 3, '{"v":1,"pvs":[]}', 5)])
    rows = merge_deltas(canonical, [d1], max_bytes=50 * 1024 * 1024)
    assert rows == 1
    conn = sqlite3.connect(canonical)
    assert conn.execute(
        "SELECT payload FROM eval_cache WHERE zobrist=7"
    ).fetchone()[0] == '{"v":1,"pvs":[]}'
    conn.close()
