"""
Title: eval_cache.py — Persistent lc0 evaluation cache (issue #65)
Description:
    SQLite-backed cache of lc0 multipv analysis results keyed by
    (zobrist, network, nodes, multipv). Hits skip the engine entirely.

    Cache value stores, for each of the top PV entries, the WDL in White's
    frame plus the PV move sequence (UCI). On a hit we rebuild an
    info-list-shaped structure that the existing _analyze_one_move()
    consumes unchanged — same `.pov(color).wdl()` interface, same `pv`
    move list.

    Storage: <user-data-dir>/lc0_eval_cache.sqlite (WAL mode).
    No new pip dep — sqlite3 is stdlib.

Changelog:
    2026-05-13: Initial creation (issue #65)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chess
import chess.engine
import chess.polyglot

log = logging.getLogger(__name__)


# Cache value layout version. Bumped if the on-disk JSON shape changes.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CachedPv:
    """A single PV line within a cached eval result.

    Attributes:
        wdl_white: Wins/draws/losses in permille, from White's perspective.
        pv_uci: Sequence of UCI move strings for the principal variation
            (up to 10 plies).
    """

    wdl_white: chess.engine.Wdl
    pv_uci: list[str]


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


class _RelScore:
    """Relative score stand-in for a cached entry — returns the stored Wdl."""

    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_args: object, **_kwargs: object) -> chess.engine.Wdl:
        return self._wdl


class _PovScore:
    """PovScore-shaped object backed by stored White-frame WDL.

    Exposes `.pov(color).wdl()` so the rest of lc0._analyze_one_move can
    treat cached info entries identically to live engine info entries.
    """

    def __init__(self, wdl_white: chess.engine.Wdl) -> None:
        self._white = wdl_white
        self._black = chess.engine.Wdl(
            wins=wdl_white.losses,
            draws=wdl_white.draws,
            losses=wdl_white.wins,
        )

    def pov(self, color: chess.Color) -> _RelScore:
        return _RelScore(self._white if color == chess.WHITE else self._black)


def cached_pvs_to_info_list(entries: list[CachedPv]) -> list[dict]:
    """Convert cached PV entries into an info-list shape engine.analyse() returns.

    Args:
        entries: Up-to-3 cached PV entries in best→worst order.

    Returns:
        A list of dicts each containing keys 'score' (a PovScore-shaped
        object) and 'pv' (a list of chess.Move). Empty entries are
        represented with an empty pv list, mirroring how _analyze_arrows()
        already handles missing PV slots.
    """
    info_list: list[dict] = []
    for entry in entries:
        pv_moves = [chess.Move.from_uci(uci) for uci in entry.pv_uci]
        info_list.append({"score": _PovScore(entry.wdl_white), "pv": pv_moves})
    return info_list


def info_list_to_cached_pvs(
    info_list: list[chess.engine.InfoDict],
    *,
    max_pv_plies: int = 10,
) -> list[CachedPv]:
    """Project a live engine.analyse(multipv=N) result into cacheable PV entries.

    Args:
        info_list: Result of engine.analyse(board, limit, multipv=N).
        max_pv_plies: Truncate stored PV at this depth to bound row size.

    Returns:
        List of CachedPv entries — one per multipv slot.
    """
    out: list[CachedPv] = []
    for pv_info in info_list:
        pv = pv_info.get("pv", []) or []
        score = pv_info.get("score")
        if score is None:
            out.append(CachedPv(
                wdl_white=chess.engine.Wdl(wins=0, draws=0, losses=0),
                pv_uci=[],
            ))
            continue
        wdl_white = score.pov(chess.WHITE).wdl()
        pv_uci = [move.uci() for move in pv[:max_pv_plies]]
        out.append(CachedPv(wdl_white=wdl_white, pv_uci=pv_uci))
    return out


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
    """SQLite-backed lc0 evaluation cache.

    Thread-unsafe by design — instantiate one per worker process. Reads
    and writes are serialised through a single connection in WAL mode so
    concurrent worker processes (if ever introduced) can coexist.
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
            self._conn = sqlite3.connect(str(db_path))
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
            # Corrupt database: drop + recreate. Loss of cache is
            # cheaper than crashing a worker.
            log.warning("eval_cache: corrupt DB at %s; recreating", self.db_path)
            self._conn.close()
            self.db_path.unlink(missing_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._init_schema()

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
        cur = self._conn.execute(
            "SELECT payload FROM eval_cache "
            "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
            (zobrist, network, nodes, multipv),
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
        self._conn.execute(
            "UPDATE eval_cache SET last_used_at=? "
            "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
            (int(time.time()), zobrist, network, nodes, multipv),
        )
        self._conn.commit()
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
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_cache "
            "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (zobrist, network, nodes, multipv, payload, now, now),
        )
        self._conn.commit()

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

    def close(self) -> None:
        """Close the SQLite connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _encode_payload(entries: list[CachedPv]) -> str:
    """JSON-encode CachedPv entries for storage.

    Args:
        entries: PV entries to encode.

    Returns:
        Compact JSON string. Includes a schema_version field so future
        readers can reject incompatible payloads.
    """
    return json.dumps(
        {
            "v": SCHEMA_VERSION,
            "pvs": [
                {
                    "w": entry.wdl_white.wins,
                    "d": entry.wdl_white.draws,
                    "l": entry.wdl_white.losses,
                    "pv": entry.pv_uci,
                }
                for entry in entries
            ],
        },
        separators=(",", ":"),
    )


def _decode_payload(text: str) -> list[CachedPv]:
    """Inverse of _encode_payload. Raises ValueError on schema mismatch.

    Args:
        text: JSON string read from the eval_cache row.

    Returns:
        List of CachedPv.

    Raises:
        ValueError: When schema_version is unknown.
        KeyError, TypeError: When the payload is structurally wrong.
    """
    obj = json.loads(text)
    if obj.get("v") != SCHEMA_VERSION:
        raise ValueError(f"unsupported eval_cache schema: {obj.get('v')}")
    entries: list[CachedPv] = []
    for pv in obj["pvs"]:
        entries.append(
            CachedPv(
                wdl_white=chess.engine.Wdl(
                    wins=pv["w"], draws=pv["d"], losses=pv["l"],
                ),
                pv_uci=list(pv["pv"]),
            )
        )
    return entries
