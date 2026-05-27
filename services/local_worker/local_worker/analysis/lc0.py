"""
Title: lc0.py — Lc0 UCI analysis engine
Description:
    Runs Lc0 analysis on a PGN string via the python-chess UCI interface.
    Requests MultiPV=3 to capture candidate arrows. Produces Lc0GameResult
    with WDL scores from White's perspective and win%-delta classifications.

Changelog:
    2026-05-09: Initial creation
    2026-05-10: Fixed analyze_pgn() to only set Backend/WeightsFile/SyzygyPath
                when non-empty; empty opts dict skips configure() entirely.
    2026-05-13: _analyze_one_move() reuses the matching MultiPV entry's score
                instead of issuing a 2nd analyse() call when the played move
                appears in the top-3 PV (issue #61). Falls back to a 2nd call
                only when the move is outside the top-3 (rare). Extracted
                _build_engine_opts/_accumulate_move_stats/_build_game_result
                helpers to keep analyze_pgn under cc=10.
    2026-05-13: analyze_pgn() merges lc0_tuning auto-tuner output (Threads,
                NNCacheSize, RamLimitMb, SmartPruningFactor, plus calibrated
                MinibatchSize/MaxPrefetch when available) into the
                engine.configure() opts. Opt out with auto_tune=False
                (issue #62).
    2026-05-13: Added optional persistent EvalCache plumbing (issue #65).
                When `eval_cache` is supplied to analyze_pgn(), the
                multipv=3 "before" call is served from cache on hit and
                written on miss, keyed by (zobrist, network, nodes).
                Per-job hit rate is logged.
    2026-05-13: Short-circuit engine.analyse() on terminal boards
                (checkmate/stalemate/insufficient material). lc0 emits
                "bestmove a1a1" on terminal positions which python-chess
                raises InvalidMoveError for, killing the engine event
                loop. A synthesised terminal score (Win/Draw/Loss = mate
                outcome or draw permille) is supplied instead. Fixes #58.
    2026-05-19: launch_engine() previously measured the per-network draw-rate
                reference once per process (issue #159).
    2026-05-27 (#214): draw_rate_reference is now a worker-side constant from
                lc0_calibration.LC0_DRAW_RATE_REFERENCE; sampler removed.
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

from .lc0_calibration import (
    LC0_DRAW_RATE_REFERENCE,
    warn_if_network_mismatches_calibration,
)
from .lc0_tuning import get_tuned_opts
from ..lc0_tuning_sync import push_after_calibrate
from .eval_cache import (
    EvalCache,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
    zobrist_key,
)
from .models import Lc0GameResult, Lc0MoveResult

log = logging.getLogger(__name__)

def _parse_network_name(engine_id_name: str, weights_path: str) -> str:
    """Extract network name from Lc0 engine ID or weights file.

    Args:
        engine_id_name: Engine identification name (e.g., "Lc0 v0.30.0" or "Lc0 v0.30 (BT4)").
        weights_path: Path to the weights file, or empty string.

    Returns:
        Network name string, or empty string if none found.
    """
    network_name = ""
    try:
        # lc0 reports "Lc0 vX.Y.Z" or "Lc0 vX.Y.Z (network: <hash>)" or "Lc0 vX.Y (BT4)"
        if engine_id_name.startswith("Lc0"):
            # Try to extract a network hint from the id name in parentheses
            if "(" in engine_id_name and ")" in engine_id_name:
                network_name = engine_id_name.split("(", 1)[1].rstrip(")")
        else:
            network_name = engine_id_name

        # Fallback to weights file basename if no network name extracted
        if not network_name and weights_path:
            from pathlib import Path
            network_name = Path(weights_path).stem
    except Exception:
        pass
    return network_name


def _mover_win_pct_from_wdl(wdl: chess.engine.Wdl) -> float:
    """Win% for the mover from a WDL permille tuple (raw observable for arrows)."""
    return (wdl.wins + wdl.draws * 0.5) / 10.0


def _analyze_arrows(
    info_list: list[chess.engine.InfoDict],
    board: chess.Board,
    mover: chess.Color,
) -> tuple[list[str], list[Optional[float]], list[Optional[str]]]:
    """Extract MultiPV arrow UCIs, scores, and PV SAN continuations.

    Args:
        info_list: List of info dicts from MultiPV engine.analyse().
        board: Board position before the move (not modified).
        mover: Side to move.

    Returns:
        Tuple of (arrows, arrow_scores, pv_sans), each a list of up to 3
        entries. Empty PV slots are filled with "", None, None respectively.
    """
    arrows: list[str] = []
    arrow_scores: list[Optional[float]] = []
    pv_sans: list[Optional[str]] = []

    for pv_info in info_list[:3]:
        pv = pv_info.get("pv", [])
        if pv:
            arrows.append(pv[0].uci())
            pv_wdl = pv_info["score"].pov(mover).wdl()
            arrow_scores.append(_mover_win_pct_from_wdl(pv_wdl))
            pv_board = board.copy()
            pv_san_list: list[str] = []
            for pv_move in pv[:10]:
                try:
                    pv_san_list.append(pv_board.san(pv_move))
                    pv_board.push(pv_move)
                except Exception:
                    break
            pv_sans.append(json.dumps(pv_san_list) if pv_san_list else None)
        else:
            arrows.append("")
            arrow_scores.append(None)
            pv_sans.append(None)

    return arrows, arrow_scores, pv_sans


def _second_best_gap_from_scores(arrow_scores: list[Optional[float]]) -> Optional[float]:
    """Compute the Win% gap between the best and second-best MultiPV lines.

    Args:
        arrow_scores: Mover Win% for each PV line (up to 3). May contain None.

    Returns:
        Gap as float, or None if fewer than 2 valid scores are present.
    """
    if (
        len(arrow_scores) >= 2
        and arrow_scores[0] is not None
        and arrow_scores[1] is not None
    ):
        return arrow_scores[0] - arrow_scores[1]
    return None


def _candidate_wdl_mover(info: dict, mover: chess.Color) -> tuple[
    Optional[int], Optional[int], Optional[int],
]:
    """Extract one MultiPV candidate's WDL triple in mover frame, or all-None.

    Args:
        info: One element of the info_before_list returned by ``_multipv_before``.
        mover: Side to move at the position being evaluated.

    Returns:
        ``(win, draw, loss)`` mover-frame permille, or ``(None, None, None)``
        when the candidate has no WDL score (rare; lc0 always reports WDL).
    """
    score = info.get("score") if isinstance(info, dict) else None
    if score is None:
        return None, None, None
    try:
        wdl = score.pov(mover).wdl()
    except Exception:  # noqa: BLE001 — defensive
        return None, None, None
    return wdl.wins, wdl.draws, wdl.losses


def _build_move_result(
    *,
    ply_index: int,
    move_san: str,
    fen_before: str,
    wdl_played_mover: tuple[int, int, int],
    arrows: list[str],
    pv_sans: list[Optional[str]],
    candidate_wdls: list[tuple[Optional[int], Optional[int], Optional[int]]],
) -> Lc0MoveResult:
    """Assemble a raw Lc0MoveResult (#161 Phase H — no derivation).

    Args:
        ply_index: 1-based ply number.
        move_san: SAN notation of the played move.
        fen_before: FEN string before the move was played.
        wdl_played_mover: Played-move WDL triple in mover frame (permille).
        arrows: UCI strings for the top 3 MultiPV candidates.
        pv_sans: JSON-encoded SAN continuation for each PV line (up to 3).
        candidate_wdls: Per-candidate mover-frame WDL triples (up to 3); each
            entry is ``(win, draw, loss)`` or ``(None, None, None)``.

    Returns:
        Lc0MoveResult dataclass populated with raw observables only.
    """
    def _get(seq, idx, default=None):
        return seq[idx] if idx < len(seq) else default

    c1 = _get(candidate_wdls, 0, (None, None, None))
    c2 = _get(candidate_wdls, 1, (None, None, None))
    c3 = _get(candidate_wdls, 2, (None, None, None))
    return Lc0MoveResult(
        ply=ply_index,
        san=move_san,
        fen=fen_before,
        wdl_win=wdl_played_mover[0],
        wdl_draw=wdl_played_mover[1],
        wdl_loss=wdl_played_mover[2],
        arrow_uci_1=_get(arrows, 0, "") or "",
        arrow_uci_2=_get(arrows, 1),
        arrow_uci_3=_get(arrows, 2),
        wdl_win_1=c1[0], wdl_draw_1=c1[1], wdl_loss_1=c1[2],
        wdl_win_2=c2[0], wdl_draw_2=c2[1], wdl_loss_2=c2[2],
        wdl_win_3=c3[0], wdl_draw_3=c3[1], wdl_loss_3=c3[2],
        pv_san_1=_get(pv_sans, 0),
        pv_san_2=_get(pv_sans, 1),
        pv_san_3=_get(pv_sans, 2),
    )


def _terminal_wdl_white(board: chess.Board) -> tuple[int, int, int]:
    """Synthesise White-frame WDL permille for a terminal position.

    lc0 emits ``bestmove a1a1`` (a non-UCI null sentinel) when asked to
    search a board with no legal moves, which python-chess then raises
    ``InvalidMoveError`` on, killing the engine event loop. We avoid the
    call entirely and supply a deterministic terminal score here (#58).

    Args:
        board: Terminal board (caller has confirmed ``is_game_over()``).

    Returns:
        ``(wins, draws, losses)`` in permille from White's frame.
        Checkmate against the side to move → that side loses; any other
        terminal condition → draw.
    """
    if board.is_checkmate():
        return (0, 0, 1000) if board.turn == chess.WHITE else (1000, 0, 0)
    return (0, 1000, 0)


class _TerminalRelScore:
    """``.wdl()`` accessor returning a fixed Wdl — used by `_TerminalPovScore`."""

    def __init__(self, wdl: chess.engine.Wdl) -> None:
        self._wdl = wdl

    def wdl(self, *_a: object, **_k: object) -> chess.engine.Wdl:
        return self._wdl


class _TerminalPovScore:
    """`.pov(color).wdl()`-shaped object for a synthesised terminal score.

    Mirrors `chess.engine.PovScore.pov(...).wdl()` semantics so the rest
    of ``_analyze_one_move`` consumes it identically to a live result.
    """

    def __init__(self, wdl_white: tuple[int, int, int]) -> None:
        self._white = chess.engine.Wdl(*wdl_white)
        self._black = chess.engine.Wdl(
            wins=wdl_white[2], draws=wdl_white[1], losses=wdl_white[0],
        )

    def pov(self, color: chess.Color) -> _TerminalRelScore:
        return _TerminalRelScore(
            self._white if color == chess.WHITE else self._black
        )


def _terminal_info_list(board: chess.Board) -> list[dict]:
    """Build a single-entry info-list for a terminal `board` (#58).

    The synthetic entry has an empty `pv`, mirroring how `_analyze_arrows`
    already handles "no PV available" for a slot.

    Args:
        board: Terminal board.

    Returns:
        A one-element list shaped like ``engine.analyse(..., multipv=N)``.
    """
    return [{"score": _TerminalPovScore(_terminal_wdl_white(board)), "pv": []}]


def _multipv_before(
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

    On cache hit, rebuilds an info-list-shaped structure that the rest of
    `_analyze_one_move` consumes identically to a live engine result —
    same `.pov(color).wdl()` interface, same `pv` list of `chess.Move`.
    On miss (or when cache is disabled or the cache key cannot be formed),
    the engine is called and the result is written to the cache.

    Args:
        board: Position to analyse.
        engine: Running lc0 engine.
        limit: Node/depth budget for the live call.
        cache: EvalCache instance, or None to bypass.
        network: Resolved network name for the cache key.
        nodes: Node budget for the cache key.
        multipv: MultiPV count (both for the live call and the cache key).

    Returns:
        MultiPV info list, live or reconstructed from cache.
    """
    if board.is_game_over(claim_draw=False):
        # Never feed a terminal board to lc0 — it emits `bestmove a1a1`
        # which kills the engine event loop (issue #58). We also skip
        # the cache: terminal scores are cheap to synthesise and not
        # worth a row.
        log.debug("lc0: terminal position — skipping engine.analyse()")
        return _terminal_info_list(board)
    if cache is not None and cache.enabled and network:
        key = zobrist_key(board)
        cached = cache.get(key, network, nodes, multipv)
        if cached is not None:
            log.debug("lc0: eval_cache hit zobrist=%016x", key)
            return cached_pvs_to_info_list(cached)
    log.debug("lc0: analyse() multipv=%d starting", multipv)
    info_list = engine.analyse(board, limit, multipv=multipv)
    log.debug("lc0: analyse() multipv=%d returned", multipv)
    if cache is not None and cache.enabled and network:
        cache.put(
            zobrist_key(board), network, nodes, multipv,
            info_list_to_cached_pvs(info_list),
        )
    return info_list


def _analyze_one_move(
    board: chess.Board,
    move: chess.Move,
    ply_index: int,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    *,
    cache: Optional[EvalCache] = None,
    network: str = "",
    nodes: int = 0,
) -> Lc0MoveResult:
    """Analyse a single move and emit a raw Lc0MoveResult (#161 Phase H).

    Pushes ``move`` onto ``board`` in place. Returns played-move WDL +
    per-candidate WDL triples + arrow UCIs + PV SAN lists. No derivation
    happens here — that lives app-side in ``analysis.derivation.lc0``.

    Args:
        board: Board before the move (mutated — move is pushed at the end).
        move: The move to analyse.
        ply_index: 1-based ply number (1 = White's first move).
        engine: Running Lc0 engine instance.
        limit: Node/depth limit for analysis.
        cache: Optional eval cache; multipv=3 lookups served on hit, written
            back on miss.
        network: Resolved network name for the cache key. Empty disables
            caching for this call.
        nodes: Node budget used (cache key).

    Returns:
        Lc0MoveResult with raw observables only.
    """
    mover = board.turn
    fen_before = board.fen()
    move_san = board.san(move)

    info_before_list = _multipv_before(
        board, engine, limit,
        cache=cache, network=network, nodes=nodes, multipv=3,
    )

    arrows, _arrow_scores, pv_sans = _analyze_arrows(info_before_list, board, mover)
    candidate_wdls = [
        _candidate_wdl_mover(info, mover) for info in info_before_list[:3]
    ]

    matched_idx: Optional[int] = None
    for pv_idx, pv_info in enumerate(info_before_list[:3]):
        pv = pv_info.get("pv", [])
        if pv and pv[0] == move:
            matched_idx = pv_idx
            break

    board.push(move)

    if matched_idx is not None:
        # Fast path: the engine already evaluated the played move while
        # producing the top-3 PV result above. Its ``score`` IS the
        # post-move score from the mover's POV — no second analyse() needed.
        score_after = info_before_list[matched_idx]["score"]
    elif board.is_game_over(claim_draw=False):
        # Skip the post-move engine call on a terminal board — lc0 would
        # emit ``bestmove a1a1`` which kills the engine event loop (#58).
        score_after = _TerminalPovScore(_terminal_wdl_white(board))
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
    wdl_after_mover = score_after.pov(mover).wdl()

    return _build_move_result(
        ply_index=ply_index,
        move_san=move_san,
        fen_before=fen_before,
        wdl_played_mover=(
            wdl_after_mover.wins, wdl_after_mover.draws, wdl_after_mover.losses,
        ),
        arrows=arrows,
        pv_sans=pv_sans,
        candidate_wdls=candidate_wdls,
    )


def _configure_engine(
    engine: chess.engine.SimpleEngine,
    *,
    lc0_path: str,
    weights_path: str,
    syzygy_path: str,
    backend: str,
    auto_tune: bool,
) -> str:
    """Apply UCI options to a launched lc0 engine and resolve its network name.

    Combines caller-supplied options (Backend/WeightsFile/SyzygyPath) with
    auto-tuner output when `auto_tune` is True, then reads the engine's
    `id name` to extract the network identifier for the run.

    Args:
        engine: Already-popened lc0 engine.
        lc0_path: Path to lc0 binary (for tuner calibration).
        weights_path: Network weights path.
        syzygy_path: Syzygy tablebases path, or empty.
        backend: Lc0 backend.
        auto_tune: If True, merge tuner options.

    Returns:
        Resolved network name string ("" if unavailable).
    """
    opts = _build_engine_opts(backend, weights_path, syzygy_path)
    if auto_tune:
        _merge_tuned_opts(
            opts, lc0_path=lc0_path, weights_path=weights_path, backend=backend,
        )
    if opts:
        engine.configure(opts)
        log.info("lc0: configure complete (opts=%s)", sorted(opts.keys()))
    try:
        return _parse_network_name(engine.id.get("name", ""), weights_path)
    except Exception:
        return ""


def _merge_tuned_opts(
    base_opts: dict[str, str],
    *,
    lc0_path: str,
    weights_path: str,
    backend: str,
) -> dict[str, str]:
    """Merge auto-tuner UCI options into `base_opts` without overriding it.

    Caller-supplied keys in `base_opts` (Backend/WeightsFile/SyzygyPath) are
    preserved; tuner keys (Threads, NNCacheSize, RamLimitMb,
    SmartPruningFactor, MinibatchSize, MaxPrefetch) are added only when not
    already set.

    Args:
        base_opts: Starting dict, mutated in place and returned.
        lc0_path: Path to lc0 binary (used for calibration only).
        weights_path: Weights path (used for calibration + fingerprint).
        backend: Lc0 backend string.

    Returns:
        The same dict, with tuner-supplied keys merged in.
    """
    tuned = get_tuned_opts(
        lc0_path=lc0_path,
        weights_path=weights_path,
        backend=backend,
        gpu_name="",
        lc0_version="",
        on_calibrated=push_after_calibrate,
    )
    for key, value in tuned.items():
        base_opts.setdefault(key, value)
    return base_opts


def _build_engine_opts(
    backend: str, weights_path: str, syzygy_path: str
) -> dict[str, str]:
    """Build the UCI options dict for lc0.configure().

    Returns an empty dict when no overrides are supplied so callers can skip
    `engine.configure()` entirely (which would otherwise emit an empty
    `setoption` line).

    Args:
        backend: Lc0 backend name (e.g. 'cuda-fp16', 'metal'), or empty.
        weights_path: Path to network weights, or empty for engine default.
        syzygy_path: Path to Syzygy tablebases, or empty for none.

    Returns:
        Dict suitable for `engine.configure()`.
    """
    opts: dict[str, str] = {}
    if backend:
        opts["Backend"] = backend
    if weights_path:
        opts["WeightsFile"] = weights_path
    if syzygy_path:
        opts["SyzygyPath"] = syzygy_path
    return opts



def launch_engine(
    *,
    lc0_path: str,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "cpu",
    auto_tune: bool = True,
) -> tuple[chess.engine.SimpleEngine, str]:
    """Launch + configure a long-lived lc0 engine for batch reuse.

    Pays the cold-start cost (process launch, weights load, CUDA backend,
    syzygy reopen, tuner calibration) exactly once. Returns ``(engine,
    network_name)``. As of #214 the draw-rate reference is a worker-side
    constant (``LC0_DRAW_RATE_REFERENCE`` in
    ``local_worker.analysis.lc0_calibration``) paired with the BT4 network
    config; the worker no longer measures, caches, or fetches it on launch.

    Args:
        lc0_path: Absolute path to the lc0 binary.
        weights_path: Path to network weights file, or empty for default.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        backend: Lc0 backend ('cuda-auto', 'metal', 'cpu').
        auto_tune: Merge auto-tuner UCI options into ``engine.configure()``.

    Returns:
        ``(engine, network_name)``. Engine is fully configured and ready
        for ``analyse`` calls; ``network_name`` is the resolved identifier.
    """
    log.info("lc0: launching engine at %s", lc0_path)
    engine = chess.engine.SimpleEngine.popen_uci(lc0_path)
    log.info("lc0: engine launched; configuring backend=%s weights=%s syzygy=%s",
             backend or "(default)", weights_path or "(default)",
             syzygy_path or "(none)")
    try:
        network_name = _configure_engine(
            engine,
            lc0_path=lc0_path,
            weights_path=weights_path,
            syzygy_path=syzygy_path,
            backend=backend,
            auto_tune=auto_tune,
        )
    except BaseException:
        # Configure failed mid-flight — don't leak the subprocess.
        try:
            engine.quit()
        except Exception:  # noqa: BLE001
            pass
        raise
    # #214 guard: the pinned LC0_DRAW_RATE_REFERENCE is a BT4-specific
    # constant; warn loudly if the resolved network is not BT4 so a silent
    # network swap doesn't bias WDL calibration for every analysed game.
    warn_if_network_mismatches_calibration(network_name)
    return engine, network_name


def _resolve_engine_context(
    engine: Optional[chess.engine.SimpleEngine],
    network_name_override: str,
    lc0_path: str,
    weights_path: str,
    syzygy_path: str,
    backend: str,
    auto_tune: bool,
) -> tuple[chess.engine.SimpleEngine, str, bool]:
    """Resolve the active engine, network name, and ownership.

    When ``engine`` is None, launches a new engine process (caller must quit
    it). When ``engine`` is provided, reuses it as-is (caller owns lifecycle).

    Args:
        engine: Optional caller-owned engine to reuse. None means launch a
            fresh process.
        network_name_override: Network name to use when reusing a caller-owned
            engine (ignored when engine is None).
        lc0_path: Path to the lc0 binary (used only when launching).
        weights_path: Path to weights file (used only when launching).
        syzygy_path: Path to Syzygy tablebases (used only when launching).
        backend: Lc0 backend string (used only when launching).
        auto_tune: Whether to apply auto-tuner UCI options (used only when
            launching).

    Returns:
        ``(active_engine, network_name, owns_engine)``.
    """
    if engine is None:
        active_engine, network_name = launch_engine(
            lc0_path=lc0_path,
            weights_path=weights_path,
            syzygy_path=syzygy_path,
            backend=backend,
            auto_tune=auto_tune,
        )
        return active_engine, network_name, True
    # Caller-owned engine: skip launch + configure entirely. SimpleEngine
    # re-issues a full ``position fen …`` command on every ``analyse()`` call
    # so search state resets implicitly between games; the NNCache is
    # intentionally left warm so cached evals carry across games (#117).
    return engine, network_name_override, False


def _log_eval_cache_stats(eval_cache: Optional[EvalCache]) -> None:
    """Log eval-cache hit/miss statistics and reset per-job counters.

    A no-op when ``eval_cache`` is None or the cache is disabled.

    Args:
        eval_cache: The EvalCache instance for the current job, or None.
    """
    if eval_cache is not None and eval_cache.enabled:
        stats = eval_cache.stats()
        log.info(
            "lc0: eval_cache hits=%d misses=%d (%.1f%% hit rate)",
            stats.hits, stats.misses,
            100.0 * stats.hits / max(1, stats.hits + stats.misses),
        )
        eval_cache.reset_counters()


def analyze_pgn(
    pgn_text: str,
    lc0_path: str,
    nodes: int = 10000,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "cpu",
    progress_callback: Optional[Callable[..., None]] = None,
    auto_tune: bool = True,
    eval_cache: Optional[EvalCache] = None,
    engine: Optional[chess.engine.SimpleEngine] = None,
    network_name_override: str = "",
    draw_rate_reference: float = LC0_DRAW_RATE_REFERENCE,
) -> Lc0GameResult:
    """Analyse a PGN game with Lc0 and return raw per-move WDL observables.

    Args:
        pgn_text: Full PGN string for the game.
        lc0_path: Absolute path to the lc0 binary.
        nodes: Node budget per move (default 10000).
        weights_path: Path to network weights file, or empty for default.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        backend: Lc0 backend ('cuda-auto', 'metal', 'cpu').
        progress_callback: Optional callable(ply, total_plies, san, fen, ...)
            called once per analysed move.
        auto_tune: Merge auto-tuner UCI options into ``engine.configure()``.
        eval_cache: Optional shared NN-eval cache for multipv lookups.
        engine: Optional pre-launched, pre-configured engine (the run loop
            owns its lifecycle when provided).
        network_name_override: When ``engine`` is reused, the resolved
            network name to pass through instead of re-reading engine.id.
        draw_rate_reference: Echoed verbatim into the result for the app's
            derivation layer (#161 Phase B attaches it to each job at
            checkout time). Worker doesn't compute or apply it.

    Returns:
        Lc0GameResult with raw observables only.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(game.mainline_moves())
    total_plies = len(moves_list)

    if total_plies == 0:
        # Refuse to submit empty analysis (run_one_job will fail() the job).
        raise ValueError("PGN has no moves — cannot analyse a 0-ply game")

    active_engine, network_name, owns_engine = _resolve_engine_context(
        engine, network_name_override,
        lc0_path, weights_path, syzygy_path, backend, auto_tune,
    )
    log.info(
        "lc0: analyzing game network=%s nodes=%d draw_rate_ref=%.4f plies=%d",
        network_name, nodes, draw_rate_reference, total_plies,
    )
    try:
        board = game.board()
        move_results: list[Lc0MoveResult] = []
        limit = chess.engine.Limit(nodes=nodes)
        for ply_index, move in enumerate(moves_list, start=1):
            ply_started = time.monotonic()
            move_result = _analyze_one_move(
                board, move, ply_index, active_engine, limit,
                cache=eval_cache, network=network_name, nodes=nodes,
            )
            ply_seconds = time.monotonic() - ply_started
            move_results.append(move_result)
            if progress_callback:
                progress_callback(
                    ply_index, total_plies, move_result.san, board.fen(),
                    nodes=nodes, seconds=ply_seconds,
                )
        _log_eval_cache_stats(eval_cache)
        return Lc0GameResult(
            engine_nodes=nodes,
            network_name=network_name,
            draw_rate_reference=draw_rate_reference,
            moves=move_results,
        )
    finally:
        if owns_engine:
            active_engine.quit()


def build_lc0_payload(result: Lc0GameResult, *, worker_id: str) -> dict:
    """Serialize an Lc0GameResult into the #161 raw API payload.

    Args:
        result: Lc0GameResult from analyze_pgn() — raw observables only.
        worker_id: Worker identifier string.

    Returns:
        Dict matching Lc0CompleteSerializer's raw-only schema. Derivation
        runs app-side via ``analysis.derivation.lc0``.
    """
    return {
        "engine": "lc0",
        "worker_id": worker_id,
        "engine_nodes": result.engine_nodes,
        "network_name": result.network_name,
        "draw_rate_reference": result.draw_rate_reference,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "wdl_win": m.wdl_win,
                "wdl_draw": m.wdl_draw,
                "wdl_loss": m.wdl_loss,
                "arrow_uci_1": m.arrow_uci_1,
                "arrow_uci_2": m.arrow_uci_2,
                "arrow_uci_3": m.arrow_uci_3,
                "wdl_win_1": m.wdl_win_1,
                "wdl_draw_1": m.wdl_draw_1,
                "wdl_loss_1": m.wdl_loss_1,
                "wdl_win_2": m.wdl_win_2,
                "wdl_draw_2": m.wdl_draw_2,
                "wdl_loss_2": m.wdl_loss_2,
                "wdl_win_3": m.wdl_win_3,
                "wdl_draw_3": m.wdl_draw_3,
                "wdl_loss_3": m.wdl_loss_3,
                "pv_san_1": m.pv_san_1,
                "pv_san_2": m.pv_san_2,
                "pv_san_3": m.pv_san_3,
            }
            for m in result.moves
        ],
    }
