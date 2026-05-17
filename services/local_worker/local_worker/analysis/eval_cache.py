"""
Title: eval_cache.py — Persistent engine evaluation cache (issues #65, #67)
Description:
    SQLite-backed cache of engine multipv analysis results keyed by
    (zobrist, network, nodes, multipv). Hits skip the engine entirely.

    Originally lc0-only: stored WDL in White's frame plus the PV move
    sequence (UCI). Issue #67 generalises the schema to also cover
    Stockfish, which speaks centipawns + mate distance rather than WDL.

    The pure value layer (CachedPv, the lc0/Stockfish score adapters,
    and JSON payload encode/decode) lives in ``_eval_cache_codec`` and
    is re-exported here, so every existing
    ``from local_worker.analysis.eval_cache import ...`` keeps working.
    This module owns only the SQLite storage engine + Zobrist keying.

    Cross-engine isolation is provided by the `network` column: lc0
    keys use the network name as-is; Stockfish keys are prefixed with
    "sf:<engine-id-name>" so they cannot collide with an lc0 entry at
    the same Zobrist.

    Storage: <user-data-dir>/eval_cache.sqlite (WAL mode).
    No new pip dep — sqlite3 is stdlib.

Changelog:
    2026-05-13: Initial creation (issue #65)
    2026-05-13: Wrap zobrist to signed 64-bit at the SQLite binding layer
                (issue #77).
    2026-05-13: SCHEMA_VERSION=2; CachedPv gained optional cp_white +
                mate_white (issue #67).
    2026-05-16: O4 — busy_timeout, best-effort degrade under writer
                contention, and NEVER unlink a corrupt shared DB
                (concurrent SF workers may hold it open). Pure value
                layer extracted to _eval_cache_codec (#130).
"""
from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chess
import chess.polyglot

from ._eval_cache_codec import (
    SCHEMA_VERSION,
    CachedPv,
    EngineKind,
    _decode_payload,
    _encode_payload,
    _PovScore,
    _RelScore,
    _stockfish_povscore_from_cached,
    _wdl_from_score,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
)

__all__ = [
    "SCHEMA_VERSION",
    "CachedPv",
    "CacheStats",
    "EngineKind",
    "EvalCache",
    "cached_pvs_to_info_list",
    "info_list_to_cached_pvs",
    "zobrist_key",
    "_to_signed64",
    # Re-exported pure helpers (kept importable for existing callers/tests).
    "_decode_payload",
    "_encode_payload",
    "_PovScore",
    "_RelScore",
    "_stockfish_povscore_from_cached",
    "_wdl_from_score",
]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CacheStats:
    """Cache runtime counters + on-disk footprint.

    Attributes:
        hits: Number of successful lookups in this process.
        misses: Number of misses in this process.
        rows: Total rows currently in the table.
        size_bytes: On-disk size of the SQLite file.
    """

    hits: int
    misses: int
    rows: int
    size_bytes: int


def _to_signed64(unsigned: int) -> int:
    """Wrap a 64-bit unsigned int into a signed int for SQLite storage.

    SQLite's INTEGER affinity stores signed 64-bit values; the Python sqlite3
    driver raises OverflowError when bound a value >= 2**63. Zobrist hashes
    are 64-bit unsigned, so half of all positions exceed that bound. The
    two-complement wrap is reversible (`_to_signed64` is its own inverse for
    values in [0, 2**64)) so existing rows whose key happened to fit signed
    range remain readable.
    """
    return unsigned - (1 << 64) if unsigned >> 63 else unsigned


def zobrist_key(board: chess.Board) -> int:
    """Return the Polyglot Zobrist hash for a position.

    Hash is transposition-aware: two move orders reaching the same board
    state produce the same key.

    Args:
        board: Position to key.

    Returns:
        64-bit unsigned Zobrist hash as a Python int.
    """
    return chess.polyglot.zobrist_hash(board)


class EvalCache:
    """SQLite-backed engine evaluation cache.

    Thread-unsafe by design — instantiate one per worker process. Reads
    and writes are serialised through a single connection in WAL mode so
    concurrent worker processes can coexist (busy_timeout + best-effort
    degrade absorb writer contention; see O4).
    """

    def __init__(self, db_path: Path, *, enabled: bool = True) -> None:
        """Open (or create) the cache database.

        Args:
            db_path: SQLite file path. Parent dir is created if missing.
            enabled: If False, all get()/put() calls are no-ops. Useful
                for benchmark runs.
        """
        self.db_path = db_path
        self.enabled = enabled
        self._hits = 0
        self._misses = 0
        self._conn: Optional[sqlite3.Connection] = None
        if enabled:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), timeout=5.0)
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._init_schema()

    def _init_schema(self) -> None:
        """Create the table + indexes if missing. Enable WAL."""
        assert self._conn is not None
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_cache (
                    zobrist INTEGER NOT NULL,
                    network TEXT NOT NULL,
                    nodes INTEGER NOT NULL,
                    multipv INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    last_used_at INTEGER NOT NULL,
                    PRIMARY KEY (zobrist, network, nodes, multipv)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_last_used "
                "ON eval_cache(last_used_at)"
            )
            self._conn.commit()
        except sqlite3.DatabaseError:
            # Corrupt/unreadable DB. NEVER unlink — other worker
            # processes may hold this shared file open (O4). Disable
            # this process's cache instead; true corruption is repaired
            # offline (the canonical is rebuilt server-side between
            # campaigns).
            log.warning(
                "eval_cache: corrupt/unreadable DB at %s; disabling cache "
                "for this process (file left intact)", self.db_path,
            )
            try:
                if self._conn is not None:
                    self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
            self.enabled = False

    def get(
        self,
        zobrist: int,
        network: str,
        nodes: int,
        multipv: int,
    ) -> Optional[list[CachedPv]]:
        """Look up a cached eval. Updates last_used_at on hit.

        Args:
            zobrist: 64-bit position hash.
            network: Resolved network name (must match what was stored).
            nodes: Node budget that produced the entry.
            multipv: MultiPV count.

        Returns:
            List of CachedPv on hit, None on miss. Returns None when the
            cache is disabled or when the stored payload is unparseable.
        """
        if not self.enabled or self._conn is None:
            return None
        zobrist_signed = _to_signed64(zobrist)
        cur = self._conn.execute(
            "SELECT payload FROM eval_cache "
            "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
            (zobrist_signed, network, nodes, multipv),
        )
        row = cur.fetchone()
        if row is None:
            self._misses += 1
            return None
        try:
            entries = _decode_payload(row[0])
        except (ValueError, KeyError, TypeError):
            self._misses += 1
            return None
        try:
            self._conn.execute(
                "UPDATE eval_cache SET last_used_at=? "
                "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
                (int(time.time()), zobrist_signed, network, nodes, multipv),
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            # Lock contention from a concurrent SF worker. The cache is
            # an optimization — skip the last_used_at bump, still serve
            # the hit. (O4 best-effort degrade.)
            log.debug("eval_cache: skipped last_used_at under lock: %s", exc)
        self._hits += 1
        return entries

    def put(
        self,
        zobrist: int,
        network: str,
        nodes: int,
        multipv: int,
        entries: list[CachedPv],
    ) -> None:
        """Insert or replace a cached eval.

        Args:
            zobrist: 64-bit position hash.
            network: Resolved network name.
            nodes: Node budget used.
            multipv: MultiPV count.
            entries: PV entries to store, in best→worst order.
        """
        if not self.enabled or self._conn is None:
            return
        now = int(time.time())
        payload = _encode_payload(entries)
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO eval_cache "
                "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_to_signed64(zobrist), network, nodes, multipv, payload, now, now),
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            # Concurrent-writer lock; dropping one cache write is
            # harmless (O4 best-effort degrade).
            log.debug("eval_cache: skipped put under lock: %s", exc)

    def stats(self) -> CacheStats:
        """Return current hit/miss counters and on-disk footprint."""
        if not self.enabled or self._conn is None:
            return CacheStats(hits=0, misses=0, rows=0, size_bytes=0)
        cur = self._conn.execute("SELECT COUNT(*) FROM eval_cache")
        rows = int(cur.fetchone()[0])
        size_bytes = self.db_path.stat().st_size if self.db_path.exists() else 0
        return CacheStats(
            hits=self._hits, misses=self._misses, rows=rows, size_bytes=size_bytes,
        )

    def clear(self) -> None:
        """Delete all cached entries; keeps the schema."""
        if not self.enabled or self._conn is None:
            return
        self._conn.execute("DELETE FROM eval_cache")
        self._conn.commit()

    def prune(self, max_bytes: int, *, target_bytes: Optional[int] = None) -> int:
        """LRU-evict rows once the file exceeds `max_bytes`.

        Args:
            max_bytes: Threshold above which pruning runs.
            target_bytes: Stop pruning when file falls under this size
                (defaults to 80% of `max_bytes`).

        Returns:
            Number of rows deleted.
        """
        if not self.enabled or self._conn is None:
            return 0
        if not self.db_path.exists() or self.db_path.stat().st_size <= max_bytes:
            return 0
        target = target_bytes if target_bytes is not None else int(max_bytes * 0.8)
        deleted = 0
        # Evict oldest 5% at a time until under target. VACUUMing inside
        # the loop would defeat the WAL — VACUUM once at the end.
        while self.db_path.stat().st_size > target:
            cur = self._conn.execute("SELECT COUNT(*) FROM eval_cache")
            total = int(cur.fetchone()[0])
            if total == 0:
                break
            batch = max(1, total // 20)
            self._conn.execute(
                "DELETE FROM eval_cache WHERE rowid IN ("
                "SELECT rowid FROM eval_cache ORDER BY last_used_at ASC LIMIT ?)",
                (batch,),
            )
            self._conn.commit()
            deleted += batch
        self._conn.execute("VACUUM")
        return deleted

    def reset_counters(self) -> None:
        """Zero the in-process hit/miss counters (e.g. between jobs)."""
        self._hits = 0
        self._misses = 0

    @property
    def hits(self) -> int:
        """Return the in-process count of successful lookups."""
        return self._hits

    @property
    def lookups(self) -> int:
        """Return the in-process total of ``get()`` calls (hits + misses).

        Exposed so the worker loop can record a hit-rate sample before
        closing the cache between jobs (issue #85).
        """
        return self._hits + self._misses

    def close(self) -> None:
        """Close the SQLite connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
