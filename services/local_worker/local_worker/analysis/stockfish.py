"""
Title: stockfish.py — Stockfish UCI analysis engine
Description:
    Runs Stockfish analysis on a PGN string via the python-chess UCI interface.
    Produces a StockfishGameResult with per-move evaluations and classifications
    that conform exactly to services/app/documentation/analysis-math.md:
      - cp values are stored from White's frame; mover-perspective is derived
        via cpl_from_evals() and pov(mover).
      - Capture/sacrifice detection uses SEE (analysis/see.py).
      - Game accuracy uses the Lichess game-wide volatility-windowing scheme:
        a single interleaved all_win_pcts list (White-frame, length=plies+1)
        and per-player mover_ply_indices lists are passed to game_accuracy().
      - ACPL is per-player.

Changelog:
    2026-05-09: Initial creation
    2026-05-10: Updated analyze_pgn() to build game-wide all_win_pcts and
                per-player mover_ply_indices; game_accuracy() called with
                new Lichess-aligned API.
    2026-05-10: Removed MultiPV from engine.configure() — python-chess treats
                it as a managed option; it is passed directly to analyse().
    2026-05-13: _analyze_one_move() reuses the matching MultiPV entry's score
                instead of issuing a 2nd analyse() call when the played move
                appears in the top-3 PV (issues #67/#61). Falls back to the
                second analyse() call only when the move is outside the
                top-3 (rare). total_cpl() in _stockfish_helpers.py was
                refactored to take ``score_after: PovScore`` directly so
                the fast path needn't synthesise a dict.
    2026-05-13: analyze_pgn() gained auto_tune flag (issue #67); when True,
                heuristic Threads/Hash from stockfish_tuning.get_tuned_opts()
                are merged via setdefault so caller-supplied values win.
    2026-05-13: Added persistent EvalCache plumbing for Stockfish (issue #67,
                builds on #65). The multipv=3 "before" call is now served
                from cache on hit and written on miss, keyed by
                (zobrist, "sf:<engine-id-name>", depth, multipv). Per-job
                hit rate is logged, mirroring the lc0 path. The "sf:"
                prefix isolates SF entries from lc0 entries at the same
                zobrist. NOTE: when EvalFile (NNUE) is configurable in a
                future change, fold its hash into the network key.
"""
from __future__ import annotations

import io
import json
import logging
import time
from typing import Callable, Optional

import chess
import chess.engine
import chess.pgn

from ._stockfish_helpers import mover_cp, white_cp
from .eval_cache import (
    EvalCache,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
    zobrist_key,
)
from .math import win_pct
from .models import StockfishGameResult, StockfishMoveResult
from .stockfish_tuning import get_tuned_opts

# Cap how many SAN plies are stored per PV continuation. Matches the lc0 path
# (lc0.py::_extract_arrows_and_pvs) so the UI can render both engines uniformly.
_PV_SAN_DEPTH = 10

log = logging.getLogger(__name__)


def _extract_arrows_and_pvs(
    info_list: list,
    board: chess.Board,
    mover: chess.Color,
) -> tuple[list[str], list[Optional[float]], list[Optional[str]]]:
    """Extract MultiPV arrow UCIs, mover-frame Win% scores, and PV SAN lines.

    Mirrors lc0._extract_arrows_and_pvs but converts each PV's cp evaluation
    (White's frame) into mover Win% via white_cp -> mover_cp -> win_pct.

    Args:
        info_list: MultiPV result list from engine.analyse(..., multipv=N).
        board: Position before the move (not mutated).
        mover: Side to move.

    Returns:
        Tuple of (arrows, arrow_scores, pv_sans), each up to 3 entries. Missing
        slots are "", None, None respectively.
    """
    arrows: list[str] = []
    arrow_scores: list[Optional[float]] = []
    pv_sans: list[Optional[str]] = []

    for pv_info in info_list[:3]:
        pv = pv_info.get("pv") or []
        if not pv:
            arrows.append("")
            arrow_scores.append(None)
            pv_sans.append(None)
            continue

        arrows.append(pv[0].uci())
        pv_cp_white = white_cp(pv_info["score"])
        arrow_scores.append(win_pct(mover_cp(pv_cp_white, mover)))

        pv_board = board.copy()
        pv_san_list: list[str] = []
        for pv_move in pv[:_PV_SAN_DEPTH]:
            try:
                pv_san_list.append(pv_board.san(pv_move))
                pv_board.push(pv_move)
            except Exception:
                break
        pv_sans.append(json.dumps(pv_san_list) if pv_san_list else None)

    return arrows, arrow_scores, pv_sans


def _mate_in_from_score(score: chess.engine.PovScore) -> Optional[int]:
    """Extract signed mate distance from a PovScore in White's frame.

    Args:
        score: PovScore from engine.analyse() output.

    Returns:
        Signed mate distance (positive = White mates) or None when no mate.
    """
    try:
        rel = score.pov(chess.WHITE)
        return rel.mate()
    except Exception:  # noqa: BLE001
        return None


def _build_move_result(
    *,
    san: str,
    fen_before: str,
    cp_eval_after_white: int,
    mate_in_white: Optional[int],
    arrows: list[str],
    arrow_scores: list[Optional[float]],
    pv_sans: list[Optional[str]],
) -> StockfishMoveResult:
    """Assemble a raw StockfishMoveResult (#161 Phase H — no derivation).

    Args:
        san: SAN of the played move.
        fen_before: FEN before the move was played.
        cp_eval_after_white: White-frame cp evaluation after the move
            (mate flattened to ±MATE_SCORE by the caller — the raw flag is
            ``mate_in_white``).
        mate_in_white: Signed mate distance (positive = White mates), or None.
        arrows: UCI strings for the top up-to-3 MultiPV candidate moves.
        arrow_scores: Mover-frame Win% for each PV line (raw observable).
        pv_sans: JSON-encoded SAN continuations for each PV line.

    Returns:
        StockfishMoveResult with ply=0 (caller sets the real ply_index).
    """
    def _get(seq, idx, default=None):
        return seq[idx] if idx < len(seq) else default

    return StockfishMoveResult(
        ply=0,
        san=san,
        fen=fen_before,
        cp_eval=cp_eval_after_white,
        mate_in=mate_in_white,
        arrow_uci_1=_get(arrows, 0, "") or "",
        arrow_uci_2=_get(arrows, 1),
        arrow_uci_3=_get(arrows, 2),
        arrow_score_1=_get(arrow_scores, 0),
        arrow_score_2=_get(arrow_scores, 1),
        arrow_score_3=_get(arrow_scores, 2),
        pv_san_1=_get(pv_sans, 0),
        pv_san_2=_get(pv_sans, 1),
        pv_san_3=_get(pv_sans, 2),
    )


def _multipv_before_sf(
    board: chess.Board,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    *,
    cache: Optional[EvalCache],
    network: str,
    nodes: int,
    multipv: int,
) -> list[dict]:
    """Return the engine's MultiPV result for `board`, using the cache when warm.

    Stockfish counterpart of lc0._multipv_before. On cache hit, rebuilds an
    info-list whose entries carry real ``chess.engine.PovScore`` objects so
    ``white_cp(...)`` / mate handling behaves identically to a live result.
    On miss (or when caching is disabled or the network key is empty), the
    engine is called and the result is written back to the cache.

    Args:
        board: Position to analyse.
        engine: Running Stockfish engine.
        limit: Depth/time/nodes budget for the live call.
        cache: EvalCache instance, or None to bypass.
        network: Stockfish identifier for the cache key (typically
            ``"sf:<engine-id-name>"``). Empty string disables caching.
        nodes: Cache key column reused here for depth so different depth
            settings produce separate cache entries.
        multipv: MultiPV count.

    Returns:
        MultiPV info list, live or reconstructed from cache.
    """
    if cache is not None and cache.enabled and network:
        key = zobrist_key(board)
        cached = cache.get(key, network, nodes, multipv)
        if cached is not None:
            log.debug("stockfish: eval_cache hit zobrist=%016x", key)
            return cached_pvs_to_info_list(cached, engine="stockfish")
    info_list = engine.analyse(board, limit, multipv=multipv)
    if cache is not None and cache.enabled and network:
        cache.put(
            zobrist_key(board), network, nodes, multipv,
            info_list_to_cached_pvs(info_list, engine="stockfish"),
        )
    return info_list  # type: ignore[return-value]


def _analyze_one_move(
    board: chess.Board,
    move: chess.Move,
    mover: chess.Color,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    *,
    cache: Optional[EvalCache] = None,
    network: str = "",
    depth_key: int = 0,
) -> StockfishMoveResult:
    """Analyse a single move and emit a raw StockfishMoveResult (#161 Phase H).

    Pushes ``move`` onto ``board`` in place. Returns white-frame cp_eval +
    mate_in + top-3 candidate UCIs + mover-frame arrow_score Win% + PV SAN
    lists. All derivation (CPL, classification, accuracy) runs app-side
    via ``analysis.derivation.stockfish``.

    Args:
        board: Position before the move (will be mutated by push).
        move: The move to analyse.
        mover: The colour making the move.
        engine: Configured Stockfish engine instance.
        limit: Engine search limit (depth/time/nodes).
        cache: Optional persistent eval cache.
        network: Stockfish identifier for the cache key.
        depth_key: Cache key column for the SF depth.

    Returns:
        StockfishMoveResult with raw observables only.
    """
    fen_before = board.fen()
    move_san = board.san(move)

    info_before = _multipv_before_sf(
        board, engine, limit,
        cache=cache, network=network, nodes=depth_key, multipv=3,
    )
    arrows, arrow_scores, pv_sans = _extract_arrows_and_pvs(info_before, board, mover)

    matched_idx: Optional[int] = None
    for pv_idx, pv_info in enumerate(info_before[:3]):
        pv = pv_info.get("pv") or []
        if pv and pv[0] == move:
            matched_idx = pv_idx
            break

    board.push(move)

    if matched_idx is not None:
        score_after = info_before[matched_idx]["score"]
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
    eval_after_white = white_cp(score_after)
    mate_in_white = _mate_in_from_score(score_after)

    return _build_move_result(
        san=move_san,
        fen_before=fen_before,
        cp_eval_after_white=eval_after_white,
        mate_in_white=mate_in_white,
        arrows=arrows,
        arrow_scores=arrow_scores,
        pv_sans=pv_sans,
    )


def _build_engine_opts(
    *,
    threads: Optional[int],
    hash_mb: Optional[int],
    syzygy_path: str,
    auto_tune: bool,
) -> dict:
    """Compose the UCI option dict passed to engine.configure().

    Caller-supplied threads and hash_mb (when not None) take priority over
    auto_tune output. When auto_tune is True, missing slots are filled by
    stockfish_tuning.get_tuned_opts(). A safe baseline of Threads=4/Hash=512
    is applied last so non-tuned, no-override invocations still configure.

    Args:
        threads: Caller's Threads value, or None to defer to tuner/baseline.
        hash_mb: Caller's Hash value (MB), or None to defer.
        syzygy_path: Tablebase directory; empty string skips SyzygyPath.
        auto_tune: When True, merge get_tuned_opts() via setdefault.

    Returns:
        Mapping of UCI option name to value (str or int) ready to pass to
        chess.engine.SimpleEngine.configure().
    """
    opts: dict = {}
    if threads is not None:
        opts["Threads"] = threads
    if hash_mb is not None:
        opts["Hash"] = hash_mb
    if syzygy_path:
        opts["SyzygyPath"] = syzygy_path
    if auto_tune:
        for tuned_key, tuned_value in get_tuned_opts().items():
            opts.setdefault(tuned_key, tuned_value)
    opts.setdefault("Threads", 4)
    opts.setdefault("Hash", 512)
    # #188 Phase A: ask SF to emit its native WDL triple on every analyse().
    opts.setdefault("UCI_ShowWDL", True)
    return opts


def _resolve_sf_cache_network(engine: chess.engine.SimpleEngine) -> str:
    """Build the cache network key from the running engine's UCI id name.

    Empty/missing id yields an empty string which disables caching for
    this run (matches the lc0 contract). Future: when EvalFile (NNUE)
    becomes configurable, fold its hash in here so different nets at
    the same Stockfish version don't collide.

    Args:
        engine: Already-popened Stockfish engine.

    Returns:
        Cache key string like ``"sf:Stockfish 16"``, or ``""`` when the
        engine did not report an id name.
    """
    try:
        engine_id_name = engine.id.get("name", "") or ""
    except Exception:
        engine_id_name = ""
    return f"sf:{engine_id_name}" if engine_id_name else ""


def _log_sf_eval_cache_stats(eval_cache: Optional[EvalCache]) -> None:
    """Log per-job hit-rate and reset cache counters.

    No-op when caching is disabled or the cache is None.

    Args:
        eval_cache: Cache instance or None.
    """
    if eval_cache is None or not eval_cache.enabled:
        return
    cache_stats = eval_cache.stats()
    total = max(1, cache_stats.hits + cache_stats.misses)
    log.info(
        "stockfish: eval_cache hits=%d misses=%d (%.1f%% hit rate)",
        cache_stats.hits, cache_stats.misses, 100.0 * cache_stats.hits / total,
    )
    eval_cache.reset_counters()


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: Optional[int] = None,
    hash_mb: Optional[int] = None,
    syzygy_path: str = "",
    progress_callback: Optional[Callable[..., None]] = None,
    auto_tune: bool = True,
    eval_cache: Optional[EvalCache] = None,
) -> StockfishGameResult:
    """Analyse a PGN game with Stockfish per analysis-math.md.

    Args:
        pgn_text: Full PGN string for the game.
        stockfish_path: Absolute path to the Stockfish binary.
        depth: Analysis depth (default 20).
        threads: Engine thread count. None (default) leaves the slot open for
            the auto-tuner; pass an int to override.
        hash_mb: Engine hash table size in MB. None (default) leaves the slot
            open for the auto-tuner; pass an int to override.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        progress_callback: Optional callable(ply, total_plies) called per move.
        auto_tune: When True (default), merge heuristic UCI options from
            stockfish_tuning.get_tuned_opts() into the engine.configure()
            dict via setdefault — caller-supplied threads/hash_mb keep
            priority. Set False to bypass the tuner entirely.

    Returns:
        StockfishGameResult with raw observables only (#161 Phase H).
    """
    parsed = chess.pgn.read_game(io.StringIO(pgn_text))
    if parsed is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(parsed.mainline_moves())
    total_plies = len(moves_list)
    if total_plies == 0:
        raise ValueError("PGN has no moves — cannot analyse a 0-ply game")

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    try:
        opts = _build_engine_opts(
            threads=threads, hash_mb=hash_mb,
            syzygy_path=syzygy_path, auto_tune=auto_tune,
        )
        log.info("stockfish: configuring engine with opts=%s", opts)
        engine.configure(opts)
        engine_name = engine.id.get("name", "") if hasattr(engine, "id") else ""
        cache_network = _resolve_sf_cache_network(engine)
        # #188 Phase A: read NormalizeToPawnValue once per analysis run.
        # SF 16+ exposes this as a read-only UCI option (default ≈ 328).
        # Older builds without the option yield None — nullable end-to-end.
        npv_opt = engine.options.get("NormalizeToPawnValue")
        normalize_to_pawn_value = (
            int(npv_opt.default) if npv_opt is not None and npv_opt.default is not None
            else None
        )
        log.info("stockfish: NormalizeToPawnValue=%s", normalize_to_pawn_value)

        board = parsed.board()
        move_results: list[StockfishMoveResult] = []
        limit = chess.engine.Limit(depth=depth)

        for ply_index, move in enumerate(moves_list, start=1):
            mover = board.turn
            ply_started = time.monotonic()
            move_result = _analyze_one_move(
                board, move, mover, engine, limit,
                cache=eval_cache, network=cache_network, depth_key=depth,
            )
            ply_seconds = time.monotonic() - ply_started
            move_result.ply = ply_index
            move_results.append(move_result)
            if progress_callback:
                progress_callback(
                    ply_index, total_plies, move_result.san, board.fen(),
                    depth=depth, seconds=ply_seconds,
                )
        _log_sf_eval_cache_stats(eval_cache)
        return StockfishGameResult(
            engine_depth=depth, engine_name=engine_name, moves=move_results,
            normalize_to_pawn_value=normalize_to_pawn_value,
        )
    finally:
        engine.quit()


def build_stockfish_payload(result: StockfishGameResult, *, worker_id: str) -> dict:
    """Serialize a StockfishGameResult into the #161 raw API payload.

    Args:
        result: StockfishGameResult from analyze_pgn().
        worker_id: Worker identifier string to include in the payload.

    Returns:
        Dict matching StockfishCompleteSerializer's raw-only schema. All
        derivation runs app-side via ``analysis.derivation.stockfish``.
    """
    return {
        "engine": "stockfish",
        "worker_id": worker_id,
        "engine_depth": result.engine_depth,
        "engine_name": result.engine_name,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "cp_eval": m.cp_eval,
                "mate_in": m.mate_in,
                "arrow_uci_1": m.arrow_uci_1,
                "arrow_uci_2": m.arrow_uci_2,
                "arrow_uci_3": m.arrow_uci_3,
                "arrow_score_1": m.arrow_score_1,
                "arrow_score_2": m.arrow_score_2,
                "arrow_score_3": m.arrow_score_3,
                "pv_san_1": m.pv_san_1,
                "pv_san_2": m.pv_san_2,
                "pv_san_3": m.pv_san_3,
            }
            for m in result.moves
        ],
    }
