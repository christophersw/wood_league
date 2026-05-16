"""
Title: test_cache_sync.py — Tests for the vast.ai eval-cache sync helpers
Description:
    Tests for ``cache_sync.snapshot_db`` (WAL-safe SQLite snapshot). More test
    cases added as ``cache_sync`` grows (pull/upload operations).

Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
import sqlite3
from pathlib import Path

from local_worker.cache_sync import snapshot_db


def test_snapshot_db_produces_valid_copy_under_open_wal(tmp_path: Path):
    src = tmp_path / "eval_cache.sqlite"
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    # Leave the WAL connection OPEN to mimic a running worker.

    dst = tmp_path / "snap.sqlite"
    snapshot_db(src, dst)

    assert dst.exists()
    snap = sqlite3.connect(dst)
    rows = snap.execute("SELECT k, v FROM t").fetchall()
    assert rows == [(1, "a")]
    snap.close()
    conn.close()
