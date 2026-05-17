"""
Title: _eval_cache_codec.py — Eval-cache value layer (pure, no I/O)
Description:
    The pure value/codec half of the engine evaluation cache, split out
    of eval_cache.py so each module stays small and independently
    reviewable. Holds the CachedPv dataclass, the lc0/Stockfish score
    adapters, and the JSON payload encode/decode. No SQLite, no
    filesystem — everything here is deterministic and unit-testable in
    isolation. eval_cache.py re-exports these names, so every existing
    ``from local_worker.analysis.eval_cache import ...`` keeps working.
Changelog:
    2026-05-13: Logic originally authored in eval_cache.py (issues #65,
                #67, #77).
    2026-05-16: Extracted verbatim from eval_cache.py into this codec
                module (#130). No behaviour change.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Optional

import chess
import chess.engine

from .math import MATE_SCORE

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
