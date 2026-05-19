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
    2026-05-19: launch_engine() now measures the per-network draw-rate
                reference once per process (module-level cache) and
                returns it as the 3rd element of the return tuple. Added
                draw_rate_reference_override param to analyze_pgn() so
                callers that reuse a warm engine can pass the measured
                value through without re-measuring (issue #159).
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

from .lc0_draw_rate import DrawRateResult, measure_draw_rate
from .lc0_tuning import get_tuned_opts
from ..lc0_tuning_sync import push_after_calibrate
from .eval_cache import (
    EvalCache,
    cached_pvs_to_info_list,
    info_list_to_cached_pvs,
    zobrist_key,
)
from .math import classify_lc0_move, cp_equiv_from_q
from .models import Lc0MoveResult, Lc0GameResult
from .see import see_capture_or_sacrifice

log = logging.getLogger(__name__)

# Module-level cache: network_name -> DrawRateResult. Populated once per
# process per network so the cold-start measurement cost is paid exactly once.
_draw_rate_cache: dict[str, DrawRateResult] = {}


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
    """Win% for the current mover from WDL permille values.

    Args:
        wdl: WDL from engine (current player's perspective).

    Returns:
        Win% as 0-100.
    """
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


def _build_move_result(
    *,
    ply_index: int,
    move_san: str,
    fen_before: str,
    wdl_white: tuple[int, int, int],
    cp_eq: int,
    best_move_san: str,
    arrows: list[str],
    arrow_scores: list[Optional[float]],
    pv_sans: list[Optional[str]],
    delta_win_pct: float,
    classification: str,
) -> Lc0MoveResult:
    """Assemble a Lc0MoveResult from pre-computed analysis values.

    Args:
        ply_index: 1-based ply number.
        move_san: SAN notation of the played move.
        fen_before: FEN string before the move was played.
        wdl_white: (win, draw, loss) from White's perspective in permille.
        cp_eq: Centipawn equivalent from Q conversion.
        best_move_san: SAN of the top engine suggestion.
        arrows: UCI strings for the top 3 MultiPV moves.
        arrow_scores: Mover Win% for each PV line (up to 3).
        pv_sans: JSON-encoded SAN continuation for each PV line (up to 3).
        delta_win_pct: Mover Win% drop (>=0).
        classification: Move quality label.

    Returns:
        Lc0MoveResult dataclass.
    """
    return Lc0MoveResult(
        ply=ply_index,
        san=move_san,
        fen=fen_before,
        wdl_win=wdl_white[0],
        wdl_draw=wdl_white[1],
        wdl_loss=wdl_white[2],
        cp_equiv=cp_eq,
        best_move=best_move_san,
        arrow_uci=arrows[0] if len(arrows) > 0 else "",
        arrow_uci_2=arrows[1] if len(arrows) > 1 else "",
        arrow_uci_3=arrows[2] if len(arrows) > 2 else "",
        arrow_score_1=arrow_scores[0] if len(arrow_scores) > 0 else None,
        arrow_score_2=arrow_scores[1] if len(arrow_scores) > 1 else None,
        arrow_score_3=arrow_scores[2] if len(arrow_scores) > 2 else None,
        move_win_delta=delta_win_pct,
        classification=classification,
        pv_san_1=pv_sans[0] if len(pv_sans) > 0 else None,
        pv_san_2=pv_sans[1] if len(pv_sans) > 1 else None,
        pv_san_3=pv_sans[2] if len(pv_sans) > 2 else None,
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
) -> tuple[Lc0MoveResult, chess.Color, tuple[int, int, int]]:
    """Analyse a single move: evaluate before/after, classify, and build result.

    Pushes `move` onto `board` in place.

    Args:
        board: Board before the move (mutated — move is pushed at the end).
        move: The move to analyse.
        ply_index: 1-based ply number (1 = White's first move).
        engine: Running Lc0 engine instance.
        limit: Node/depth limit for analysis.
        cache: Optional eval cache. When set, the multipv=3 lookup is
            served from cache on hit; misses are written back.
        network: Resolved network name for the cache key. Empty disables
            caching for this call.
        nodes: Node budget used (cache key). Must match `limit.nodes` to
            avoid mixing budgets in the same cache entry.

    Returns:
        Tuple of (Lc0MoveResult, mover_color, wdl_white_after) where
        wdl_white_after is (win, draw, loss) in White's frame after the move.
    """
    mover = board.turn
    fen_before = board.fen()
    move_san = board.san(move)
    is_cap_or_sac = see_capture_or_sacrifice(board, move)

    info_before_list = _multipv_before(
        board, engine, limit,
        cache=cache, network=network, nodes=nodes, multipv=3,
    )
    wdl_before = info_before_list[0]["score"].pov(mover).wdl()
    mover_win_pct_before = _mover_win_pct_from_wdl(wdl_before)

    arrows, arrow_scores, pv_sans = _analyze_arrows(info_before_list, board, mover)
    second_best_gap = _second_best_gap_from_scores(arrow_scores)

    best_move_uci = arrows[0] if arrows else ""
    best_move_san = board.san(chess.Move.from_uci(best_move_uci)) if best_move_uci else ""

    matched_idx: Optional[int] = None
    for pv_idx, pv_info in enumerate(info_before_list[:3]):
        pv = pv_info.get("pv", [])
        if pv and pv[0] == move:
            matched_idx = pv_idx
            break

    board.push(move)

    if matched_idx is not None:
        # Fast path: the engine already evaluated the played move while
        # producing the top-3 PV result above. Its `score` represents the
        # value of choosing that move (mover POV), which is exactly the
        # "after the move is played" score — no second analyse() needed.
        score_after = info_before_list[matched_idx]["score"]
    elif board.is_game_over(claim_draw=False):
        # Skip the post-move engine call on a terminal board — lc0 would
        # emit `bestmove a1a1` which kills the engine event loop (#58).
        score_after = _TerminalPovScore(_terminal_wdl_white(board))
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
    wdl_after_mover = score_after.pov(mover).wdl()
    mover_win_pct_after = _mover_win_pct_from_wdl(wdl_after_mover)

    delta_win_pct = max(0.0, mover_win_pct_before - mover_win_pct_after)
    classification = classify_lc0_move(
        delta_win_pct=delta_win_pct,
        second_best_gap=second_best_gap,
        mover_win_pct=mover_win_pct_before,
        is_capture_or_sacrifice=is_cap_or_sac,
    )

    # WDL stored from White's perspective
    wdl_after_white = score_after.pov(chess.WHITE).wdl()
    wdl_white = (wdl_after_white.wins, wdl_after_white.draws, wdl_after_white.losses)
    cp_eq = cp_equiv_from_q((wdl_after_mover.wins - wdl_after_mover.losses) / 1000.0)

    result = _build_move_result(
        ply_index=ply_index,
        move_san=move_san,
        fen_before=fen_before,
        wdl_white=wdl_white,
        cp_eq=cp_eq,
        best_move_san=best_move_san,
        arrows=arrows,
        arrow_scores=arrow_scores,
        pv_sans=pv_sans,
        delta_win_pct=delta_win_pct,
        classification=classification,
    )
    return result, mover, wdl_white


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


def _accumulate_move_stats(
    move_result: Lc0MoveResult,
    mover: chess.Color,
    wdl_white: tuple[int, int, int],
    *,
    white_wdl: tuple[list[float], list[float], list[float]],
    black_wdl: tuple[list[float], list[float], list[float]],
    cls_counts: dict[str, dict[str, int]],
) -> None:
    """Append per-ply WDL probabilities and increment classification counts.

    Args:
        move_result: The per-move analysis result just produced.
        mover: Side that played the move.
        wdl_white: WDL (wins, draws, losses) in permille from White's frame.
        white_wdl: Per-ply White wins/draws/losses lists (mutated when mover is White).
        black_wdl: Per-ply Black wins/draws/losses lists (mutated when mover is Black).
        cls_counts: Nested {"white"|"black": {label: count}} dict (mutated).
    """
    side = "white" if mover == chess.WHITE else "black"
    if move_result.classification in cls_counts[side]:
        cls_counts[side][move_result.classification] += 1

    wdl_lists = white_wdl if mover == chess.WHITE else black_wdl
    wdl_lists[0].append(wdl_white[0] / 1000)
    wdl_lists[1].append(wdl_white[1] / 1000)
    wdl_lists[2].append(wdl_white[2] / 1000)


def _build_game_result(
    *,
    nodes: int,
    network_name: str,
    move_results: list[Lc0MoveResult],
    white_wdl: tuple[list[float], list[float], list[float]],
    black_wdl: tuple[list[float], list[float], list[float]],
    cls_counts: dict[str, dict[str, int]],
) -> Lc0GameResult:
    """Assemble the final Lc0GameResult from per-ply accumulators.

    Args:
        nodes: Node budget that was used per move.
        network_name: Resolved lc0 network name string.
        move_results: List of per-move Lc0MoveResult, in ply order.
        white_wdl: White wins/draws/losses lists (per White ply, in [0,1]).
        black_wdl: Black wins/draws/losses lists (per Black ply, in [0,1]).
        cls_counts: Classification counts keyed by side then label.

    Returns:
        Fully populated Lc0GameResult.
    """
    def _avg(lst: list[float]) -> float:
        return sum(lst) / len(lst) if lst else 0.0

    return Lc0GameResult(
        engine_nodes=nodes,
        network_name=network_name,
        white_win_prob=_avg(white_wdl[0]),
        white_draw_prob=_avg(white_wdl[1]),
        white_loss_prob=_avg(white_wdl[2]),
        black_win_prob=_avg(black_wdl[0]),
        black_draw_prob=_avg(black_wdl[1]),
        black_loss_prob=_avg(black_wdl[2]),
        white_blunders=cls_counts["white"]["Blunder"],
        white_mistakes=cls_counts["white"]["Mistake"],
        white_inaccuracies=cls_counts["white"]["Inaccuracy"],
        black_blunders=cls_counts["black"]["Blunder"],
        black_mistakes=cls_counts["black"]["Mistake"],
        black_inaccuracies=cls_counts["black"]["Inaccuracy"],
        moves=move_results,
    )


def launch_engine(
    *,
    lc0_path: str,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "cpu",
    auto_tune: bool = True,
) -> tuple[chess.engine.SimpleEngine, str, float]:
    """Launch and configure a long-lived lc0 engine for batch reuse.

    Pays the cold-start cost (process launch + weights load + CUDA backend +
    syzygy reopen + tuner calibration) exactly once. Also measures the
    per-network draw-rate reference once per process (cached in
    ``_draw_rate_cache``). Callers pass the returned engine into
    :func:`analyze_pgn` for every job in the batch and call
    ``engine.quit()`` at the end. See issue #117.

    Args:
        lc0_path: Absolute path to the lc0 binary.
        weights_path: Path to network weights file, or empty for default.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        backend: Lc0 backend ('cuda-auto', 'metal', 'cpu').
        auto_tune: Merge auto-tuner UCI options into ``engine.configure()``.

    Returns:
        Tuple of ``(engine, network_name, draw_rate_reference)``. The engine
        is fully configured and ready for ``analyse`` calls; network_name is
        the resolved identifier; draw_rate_reference is the measured draw
        fraction in (0, 1) for this network.
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
    draw_rate_reference = _get_or_measure_draw_rate(engine, network_name)
    return engine, network_name, draw_rate_reference


def _get_or_measure_draw_rate(
    engine: chess.engine.SimpleEngine,
    network_name: str,
) -> float:
    """Return the cached draw-rate for network_name, measuring if absent.

    The measurement is stored in the module-level ``_draw_rate_cache`` dict
    so it runs at most once per process per network. A measurement failure
    (unexpected exception) is caught and logged; 0.5 is returned as a safe
    fallback that keeps the rescale neutral.

    Args:
        engine: Already-configured lc0 engine to use for measurement.
        network_name: Resolved network identifier (cache key).

    Returns:
        Draw-rate reference in (0, 1).
    """
    if network_name in _draw_rate_cache:
        log.info("lc0: draw_rate_reference cache hit for net=%s", network_name)
        return _draw_rate_cache[network_name].draw_rate_reference
    try:
        result = measure_draw_rate(engine, network=network_name)
        _draw_rate_cache[network_name] = result
        return result.draw_rate_reference
    except Exception:  # noqa: BLE001 — measurement must never break analysis
        log.warning(
            "lc0: draw_rate measurement failed for net=%s; using 0.5 fallback",
            network_name,
            exc_info=True,
        )
        return 0.5


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
    draw_rate_reference_override: float = 0.0,
) -> Lc0GameResult:
    """Analyse a PGN game with Lc0 and return per-move WDL results.

    Args:
        pgn_text: Full PGN string for the game.
        lc0_path: Absolute path to the lc0 binary.
        nodes: Node budget per move (default 10000).
        weights_path: Path to network weights file, or empty for default.
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        backend: Lc0 backend ('cuda-auto', 'metal', 'cpu').
        progress_callback: Optional callable(ply, total_plies, san, fen) called
            once per analysed move. `san` is the move just played; `fen` is the
            resulting board position. Both are empty strings for legacy callers
            that only inspect ply/total.
        auto_tune: When True (default), merge auto-tuner UCI options
            (Threads, NNCacheSize, RamLimitMb, SmartPruningFactor, and — if
            calibration succeeded — MinibatchSize/MaxPrefetch) into the
            engine.configure() call. Set False to bypass the tuner entirely.
        engine: Optional pre-launched, pre-configured lc0 engine. When
            provided, this call neither launches nor quits the process —
            the caller (e.g. the batch drain loop) owns its lifecycle.
            Saves ~6 s of cold-start per game on GPU rigs (issue #117).
        network_name_override: When ``engine`` is reused, the caller already
            resolved the network name at launch — pass it through instead of
            re-reading ``engine.id``.
        draw_rate_reference_override: When ``engine`` is reused, the caller's
            measured draw-rate reference (from ``launch_engine``'s 3rd return
            element). 0.0 signals "not yet measured" — the value is ignored
            until Phase C wires the rescale consumer (issue #159).

    Returns:
        Lc0GameResult with per-move WDL evaluations and game statistics.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(game.mainline_moves())
    total_plies = len(moves_list)
    network_name = ""

    if total_plies == 0:
        # Refuse to submit empty analysis — see issue tracker. Completing a
        # 0-ply game writes a bogus row with all-zero accuracies/counts and
        # poisons the queue. Caller (run_one_job) will catch this and call
        # client.fail() so the job is requeued or surfaced.
        raise ValueError("PGN has no moves — cannot analyse a 0-ply game")

    owns_engine = engine is None
    active_engine: chess.engine.SimpleEngine
    draw_rate_reference: float
    if engine is None:
        active_engine, network_name, draw_rate_reference = launch_engine(
            lc0_path=lc0_path,
            weights_path=weights_path,
            syzygy_path=syzygy_path,
            backend=backend,
            auto_tune=auto_tune,
        )
    else:
        # Caller-owned engine: skip launch + configure entirely.
        # SimpleEngine re-issues a full ``position fen …`` command on every
        # ``analyse()`` call so search state resets implicitly between
        # games; the NNCache is intentionally left warm so cached evals
        # carry across games (it's a pure speedup, never a correctness
        # issue) — issue #117.
        active_engine = engine
        network_name = network_name_override
        draw_rate_reference = draw_rate_reference_override
    try:
        board = game.board()
        move_results: list[Lc0MoveResult] = []
        white_wdl_wins: list[float] = []
        white_wdl_draws: list[float] = []
        white_wdl_losses: list[float] = []
        black_wdl_wins: list[float] = []
        black_wdl_draws: list[float] = []
        black_wdl_losses: list[float] = []
        cls_counts: dict[str, dict[str, int]] = {
            "white": {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
            "black": {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
        }
        limit = chess.engine.Limit(nodes=nodes)
        log.info(
            "lc0: entering move loop — %d plies, %d nodes/move draw_rate_ref=%.4f",
            total_plies, nodes, draw_rate_reference,
        )

        for ply_index, move in enumerate(moves_list, start=1):
            log.info("lc0: analysing ply %d/%d", ply_index, total_plies)
            ply_started = time.monotonic()
            move_result, mover, wdl_white = _analyze_one_move(
                board, move, ply_index, active_engine, limit,
                cache=eval_cache, network=network_name, nodes=nodes,
            )
            ply_seconds = time.monotonic() - ply_started
            move_results.append(move_result)

            _accumulate_move_stats(
                move_result, mover, wdl_white,
                white_wdl=(white_wdl_wins, white_wdl_draws, white_wdl_losses),
                black_wdl=(black_wdl_wins, black_wdl_draws, black_wdl_losses),
                cls_counts=cls_counts,
            )

            if progress_callback:
                # Pass move SAN + post-move FEN so the CLI can show which move
                # just finished and render the resulting board. nodes/seconds
                # feed the issue-#44 per-ply readouts.
                progress_callback(
                    ply_index, total_plies, move_result.san, board.fen(),
                    nodes=nodes, seconds=ply_seconds,
                )

        if eval_cache is not None and eval_cache.enabled:
            stats = eval_cache.stats()
            log.info(
                "lc0: eval_cache hits=%d misses=%d (%.1f%% hit rate)",
                stats.hits, stats.misses,
                100.0 * stats.hits / max(1, stats.hits + stats.misses),
            )
            eval_cache.reset_counters()
        return _build_game_result(
            nodes=nodes,
            network_name=network_name,
            move_results=move_results,
            white_wdl=(white_wdl_wins, white_wdl_draws, white_wdl_losses),
            black_wdl=(black_wdl_wins, black_wdl_draws, black_wdl_losses),
            cls_counts=cls_counts,
        )
    finally:
        if owns_engine:
            active_engine.quit()


def build_lc0_payload(result: Lc0GameResult, *, worker_id: str) -> dict:
    """Serialize a Lc0GameResult into the API complete payload dict.

    Args:
        result: Lc0GameResult from analyze_pgn().
        worker_id: Worker identifier string.

    Returns:
        Dict matching the Lc0CompleteSerializer schema.
    """
    return {
        "engine": "lc0",
        "worker_id": worker_id,
        "engine_nodes": result.engine_nodes,
        "network_name": result.network_name,
        "white_win_prob": result.white_win_prob,
        "white_draw_prob": result.white_draw_prob,
        "white_loss_prob": result.white_loss_prob,
        "black_win_prob": result.black_win_prob,
        "black_draw_prob": result.black_draw_prob,
        "black_loss_prob": result.black_loss_prob,
        "white_blunders": result.white_blunders,
        "white_mistakes": result.white_mistakes,
        "white_inaccuracies": result.white_inaccuracies,
        "black_blunders": result.black_blunders,
        "black_mistakes": result.black_mistakes,
        "black_inaccuracies": result.black_inaccuracies,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "wdl_win": m.wdl_win,
                "wdl_draw": m.wdl_draw,
                "wdl_loss": m.wdl_loss,
                "cp_equiv": m.cp_equiv,
                "best_move": m.best_move,
                "arrow_uci": m.arrow_uci,
                "arrow_uci_2": m.arrow_uci_2,
                "arrow_uci_3": m.arrow_uci_3,
                "arrow_score_1": m.arrow_score_1,
                "arrow_score_2": m.arrow_score_2,
                "arrow_score_3": m.arrow_score_3,
                "move_win_delta": m.move_win_delta,
                "classification": m.classification,
                "pv_san_1": m.pv_san_1,
                "pv_san_2": m.pv_san_2,
                "pv_san_3": m.pv_san_3,
            }
            for m in result.moves
        ],
    }
