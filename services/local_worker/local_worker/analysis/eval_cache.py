"""
Title: eval_cache.py — Persistent engine evaluation cache (issues #65, #67)
Description:
    SQLite-backed cache of engine multipv analysis results keyed by
    (zobrist, network, nodes, multipv). Hits skip the engine entirely.

    Originally lc0-only: stored WDL in White's frame plus the PV move
    sequence (UCI). Issue #67 generalises the schema to also cover
    Stockfish, which speaks centipawns + mate distance rather than WDL.

    A CachedPv now optionally carries `cp_white` and `mate_white` (signed
    mate distance from White's frame; positive = White mates). lc0
    entries leave them as None; Stockfish entries leave `wdl_white` as a
    placeholder draw (Stockfish builds rarely expose .wdl() and we never
    consume it on the SF read path).

    Cross-engine isolation is provided by the `network` column: lc0
    keys use the network name as-is; Stockfish keys are prefixed with
    "sf:<engine-id-name>" so they cannot collide with an lc0 entry at
    the same Zobrist.

    Storage: <user-data-dir>/eval_cache.sqlite (WAL mode).
    No new pip dep — sqlite3 is stdlib.

Changelog:
    2026-05-13: Initial creation (issue #65)
    2026-05-13: SCHEMA_VERSION=2; CachedPv gained optional cp_white +
                mate_white. cached_pvs_to_info_list /
                info_list_to_cached_pvs accept engine='lc0'|'stockfish'.
                Stockfish round-trip rebuilds a real chess.engine.PovScore
                so .pov(color).score(mate_score=...) works from either
                side. v1 payloads are treated as misses (issue #67).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import chess
import chess.engine
import chess.polyglot

from .math import MATE_SCORE

log = logging.getLogger(__name__)


# Cache value layout version. Bumped if the on-disk JSON shape changes.
# v1 (lc0-only): {"v":1,"pvs":[{"w","d","l","pv"}, ...]}
# v2 (lc0 + stockfish): adds optional "cp" / "mate" keys per PV entry.
SCHEMA_VERSION = 2


# Engine identifier accepted by the encode/decode adapters.
EngineKind = Literal["lc0", "stockfish"]


@dataclass(frozen=True)
class CachedPv:
    """A single PV line within a cached eval result.

    Attributes:
        wdl_white: Wins/draws/losses in permille, from White's perspective.
            For Stockfish entries this is a placeholder (0/1000/0) since
            most SF builds don't expose .wdl() — the SF read path uses
            cp_white / mate_white instead.
        pv_uci: Sequence of UCI move strings for the principal variation
            (up to 10 plies).
        cp_white: Optional signed centipawn evaluation in White's frame,
            clamped to ±MATE_SCORE. None for lc0 entries.
        mate_white: Optional signed mate distance from White's frame:
            positive = White mates in N plies, negative = Black mates,
            None when there is no forced mate (or for lc0 entries).
    """

    wdl_white: chess.engine.Wdl
    pv_uci: list[str]
    cp_white: Optional[int] = None
    mate_white: Optional[int] = None


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
    """Relative score stand-in for a cached lc0 entry — returns the stored Wdl."""

    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_args: object, **_kwargs: object) -> chess.engine.Wdl:
        return self._wdl


class _PovScore:
    """PovScore-shaped object backed by stored White-frame WDL.

    Exposes `.pov(color).wdl()` so the rest of lc0._analyze_one_move can
    treat cached info entries identically to live engine info entries.
    Used only for lc0 entries — Stockfish entries reconstruct a real
    chess.engine.PovScore (see _stockfish_povscore_from_cached).
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


def _stockfish_povscore_from_cached(entry: CachedPv) -> chess.engine.PovScore:
    """Rebuild a real chess.engine.PovScore for a Stockfish cached PV entry.

    The score is constructed from White's frame. We use
    ``PovScore(relative, turn=WHITE)`` so the relative score IS the
    White-frame value, and ``.pov(BLACK).score()`` correctly negates it.
    Mate-distance entries (mate_white not None) take precedence over
    cp_white because Stockfish reports either-or per ply.

    Args:
        entry: Cached PV entry with cp_white and/or mate_white populated.

    Returns:
        A real ``chess.engine.PovScore`` whose ``.pov(color).score(
        mate_score=...)`` returns the same cp from either side, and
        ``.pov(color).mate()`` returns the signed mate distance from that
        colour's frame.
    """
    if entry.mate_white is not None:
        # chess.engine.Mate(plies): positive plies = the side whose POV
        # this score is in mates. With turn=WHITE, positive mate_white
        # therefore means White is mating — which matches the storage
        # convention.
        relative: chess.engine.Score = chess.engine.Mate(entry.mate_white)
    else:
        cp_value = entry.cp_white if entry.cp_white is not None else 0
        relative = chess.engine.Cp(cp_value)
    return chess.engine.PovScore(relative, chess.WHITE)


def cached_pvs_to_info_list(
    entries: list[CachedPv],
    *,
    engine: EngineKind = "lc0",
) -> list[dict]:
    """Convert cached PV entries into an info-list shape engine.analyse() returns.

    Args:
        entries: Up-to-3 cached PV entries in best→worst order.
        engine: 'lc0' (default, preserves original behaviour — score is a
            WDL-only stand-in) or 'stockfish' (score is a real
            chess.engine.PovScore built from cp/mate).

    Returns:
        A list of dicts each containing keys 'score' and 'pv' (a list of
        chess.Move). Empty entries are represented with an empty pv
        list, mirroring how _analyze_arrows() already handles missing PV
        slots.
    """
    info_list: list[dict] = []
    for entry in entries:
        pv_moves = [chess.Move.from_uci(uci) for uci in entry.pv_uci]
        if engine == "stockfish":
            score: object = _stockfish_povscore_from_cached(entry)
        else:
            score = _PovScore(entry.wdl_white)
        info_list.append({"score": score, "pv": pv_moves})
    return info_list


def _wdl_from_score(score: chess.engine.PovScore) -> chess.engine.Wdl:
    """Best-effort White-frame WDL extraction from a live engine score.

    Stockfish builds without WDL support raise (or return None) on
    ``.wdl()``; we fall back to a placeholder draw so the on-disk shape
    stays uniform. The Stockfish read path never reads this field.

    Args:
        score: PovScore from a live engine.analyse() call.

    Returns:
        A chess.engine.Wdl in White's frame, or a (0, 1000, 0) draw
        placeholder when WDL is unavailable.
    """
    try:
        return score.pov(chess.WHITE).wdl()
    except (NotImplementedError, AttributeError, ValueError):
        return chess.engine.Wdl(wins=0, draws=1000, losses=0)


def info_list_to_cached_pvs(
    info_list: list[chess.engine.InfoDict],
    *,
    max_pv_plies: int = 10,
    engine: EngineKind = "lc0",
) -> list[CachedPv]:
    """Project a live engine.analyse(multipv=N) result into cacheable PV entries.

    Args:
        info_list: Result of engine.analyse(board, limit, multipv=N).
        max_pv_plies: Truncate stored PV at this depth to bound row size.
        engine: 'lc0' (default) — only WDL + pv are extracted.
            'stockfish' — additionally extracts cp_white (signed,
            clamped to ±MATE_SCORE) and mate_white (signed plies, None
            when no mate is forced).

    Returns:
        List of CachedPv entries — one per multipv slot.
    """
    out: list[CachedPv] = []
    for pv_info in info_list:
        pv = pv_info.get("pv", []) or []
        score = pv_info.get("score")
        pv_uci = [move.uci() for move in pv[:max_pv_plies]]
        if score is None:
            out.append(CachedPv(
                wdl_white=chess.engine.Wdl(wins=0, draws=0, losses=0),
                pv_uci=pv_uci,
            ))
            continue
        if engine == "stockfish":
            cp_white = score.pov(chess.WHITE).score(mate_score=MATE_SCORE)
            mate_white = score.pov(chess.WHITE).mate()
            out.append(CachedPv(
                wdl_white=_wdl_from_score(score),
                pv_uci=pv_uci,
                cp_white=int(cp_white) if cp_white is not None else None,
                mate_white=int(mate_white) if mate_white is not None else None,
            ))
        else:
            out.append(CachedPv(
                wdl_white=score.pov(chess.WHITE).wdl(),
                pv_uci=pv_uci,
            ))
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
    """SQLite-backed engine evaluation cache.

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
        readers can reject incompatible payloads. Stockfish-only fields
        (cp / mate) are omitted when None to keep lc0 rows compact.
    """
    pvs: list[dict] = []
    for entry in entries:
        item: dict = {
            "w": entry.wdl_white.wins,
            "d": entry.wdl_white.draws,
            "l": entry.wdl_white.losses,
            "pv": entry.pv_uci,
        }
        if entry.cp_white is not None:
            item["cp"] = entry.cp_white
        if entry.mate_white is not None:
            item["mate"] = entry.mate_white
        pvs.append(item)
    return json.dumps({"v": SCHEMA_VERSION, "pvs": pvs}, separators=(",", ":"))


def _decode_payload(text: str) -> list[CachedPv]:
    """Inverse of _encode_payload. Raises ValueError on schema mismatch.

    Args:
        text: JSON string read from the eval_cache row.

    Returns:
        List of CachedPv.

    Raises:
        ValueError: When schema_version is unknown (v1 rows are treated
            as a miss by the caller; we don't transparently upgrade them
            because v1 is lc0-only and re-running lc0 once costs less
            than a stale-schema bug).
        KeyError, TypeError: When the payload is structurally wrong.
    """
    obj = json.loads(text)
    if obj.get("v") != SCHEMA_VERSION:
        raise ValueError(f"unsupported eval_cache schema: {obj.get('v')}")
    entries: list[CachedPv] = []
    for pv in obj["pvs"]:
        cp = pv.get("cp")
        mate = pv.get("mate")
        entries.append(
            CachedPv(
                wdl_white=chess.engine.Wdl(
                    wins=pv["w"], draws=pv["d"], losses=pv["l"],
                ),
                pv_uci=list(pv["pv"]),
                cp_white=int(cp) if cp is not None else None,
                mate_white=int(mate) if mate is not None else None,
            )
        )
    return entries
