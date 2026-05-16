"""
Title: cache_merge.py — offline per-instance eval-cache delta merge
Description:
    Server-side, manual, between-campaigns job. Unions per-instance
    cache deltas into the canonical eval cache using INSERT OR REPLACE
    on the (zobrist, network, nodes, multipv) primary key. The engine is
    deterministic at fixed nodes, so identical positions yield identical
    evals — last-writer-wins is correct. The canonical is then pruned to
    the size cap and vacuumed, and becomes the next campaign's
    boot-time-pull source. Intentionally one campaign behind.
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from local_worker.analysis.eval_cache import EvalCache

log = logging.getLogger(__name__)


def merge_deltas(canonical: Path, deltas: list[Path], max_bytes: int) -> int:
    """Union delta caches into the canonical, prune, vacuum.

    Args:
        canonical: Path to the canonical eval-cache SQLite file. Created
            (with schema) if it does not exist.
        deltas: Per-instance delta SQLite files, applied in list order
            (later files win on primary-key collisions).
        max_bytes: Size cap enforced via ``EvalCache.prune`` after merge.

    Returns:
        Number of rows in the canonical after merge + prune.
    """
    # Ensure canonical exists with the current schema (reuses EvalCache).
    EvalCache(canonical).close()

    conn = sqlite3.connect(str(canonical))
    try:
        for delta in deltas:
            if not Path(delta).exists():
                log.warning("cache_merge: delta missing, skipped: %s", delta)
                continue
            conn.execute("ATTACH DATABASE ? AS d", (str(delta),))
            conn.execute(
                "INSERT OR REPLACE INTO eval_cache "
                "(zobrist, network, nodes, multipv, payload, "
                " created_at, last_used_at) "
                "SELECT zobrist, network, nodes, multipv, payload, "
                "       created_at, last_used_at FROM d.eval_cache"
            )
            conn.commit()
            conn.execute("DETACH DATABASE d")
    finally:
        conn.close()

    cache = EvalCache(canonical)
    try:
        cache.prune(max_bytes)  # prune VACUUMs only if it evicted
        rows = cache.stats().rows
    finally:
        cache.close()
    # Always compact after the union (prune may not have run a VACUUM).
    vac = sqlite3.connect(str(canonical))
    try:
        vac.execute("VACUUM")
    finally:
        vac.close()
    return rows
