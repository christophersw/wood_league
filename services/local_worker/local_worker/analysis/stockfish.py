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

from ._stockfish_helpers import mover_cp, second_best_gap, total_cpl, white_cp
from .math import classify_stockfish_move, game_accuracy, move_accuracy, win_pct
from .models import StockfishGameResult, StockfishMoveResult
from .see import see_capture_or_sacrifice

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


def _build_move_result(
    *,
    san: str,
    fen_before: str,
    cp_eval_after_white: int,
    cpl: int,
    best_move_san: str,
    classification: str,
    arrows: list[str],
    arrow_scores: list[Optional[float]],
    pv_sans: list[Optional[str]],
) -> StockfishMoveResult:
    """Assemble a StockfishMoveResult from base fields and MultiPV arrays.

    Caller fills in ``ply`` afterwards. Empty MultiPV slots fall back to ""
    (arrows) and None (scores / pv_sans) — matching Lc0MoveResult's contract.

    Args:
        san: SAN of the played move.
        fen_before: FEN before the move was played.
        cp_eval_after_white: cp evaluation in White's frame after the move.
        cpl: Centipawn loss for the mover.
        best_move_san: SAN of the top engine line's first move.
        classification: Move quality label.
        arrows: UCI strings for the top up-to-3 MultiPV candidate moves.
        arrow_scores: Mover Win% for each PV line.
        pv_sans: JSON-encoded SAN continuations for each PV line.

    Returns:
        StockfishMoveResult with ply=0 (caller sets the real ply_index).
    """
    return StockfishMoveResult(
        ply=0,
        san=san,
        fen=fen_before,
        cp_eval=cp_eval_after_white,
        cpl=cpl,
        best_move=best_move_san,
        classification=classification,
        arrow_uci=arrows[0] if len(arrows) > 0 else "",
        arrow_uci_2=arrows[1] if len(arrows) > 1 else "",
        arrow_uci_3=arrows[2] if len(arrows) > 2 else "",
        arrow_score_1=arrow_scores[0] if len(arrow_scores) > 0 else None,
        arrow_score_2=arrow_scores[1] if len(arrow_scores) > 1 else None,
        arrow_score_3=arrow_scores[2] if len(arrow_scores) > 2 else None,
        pv_san_1=pv_sans[0] if len(pv_sans) > 0 else None,
        pv_san_2=pv_sans[1] if len(pv_sans) > 1 else None,
        pv_san_3=pv_sans[2] if len(pv_sans) > 2 else None,
    )


def _analyze_one_move(
    board: chess.Board,
    move: chess.Move,
    mover: chess.Color,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
) -> tuple[StockfishMoveResult, float, float, int, float]:
    """Analyse a single move and return results plus per-player accumulator values.

    Captures the SAN and SEE result before pushing the move, then analyses
    the before-position with MultiPV=3. When the played move is one of the
    top-3 PV lines (the common case in real games), the matching entry's
    ``score`` is reused as the post-move score and no second engine.analyse()
    call is issued — this halves Stockfish wall-clock per ply on the hit
    path (issues #67/#61). Misses (move outside top-3) fall back to a
    dedicated post-push analyse() call so CPL/classification stay
    bit-identical to the pre-fast-path behaviour.

    Args:
        board: Position before the move (will be mutated by push).
        move: The move to analyse.
        mover: The colour making the move.
        engine: Configured Stockfish engine instance.
        limit: Engine search limit (depth/time/nodes).

    Returns:
        Tuple of (StockfishMoveResult, move_acc, mover_win_pct_before, cpl,
        win_pct_after_white).  ``win_pct_after_white`` is Win%(eval_after_white)
        in White's frame — appended by the caller to the game-wide all_win_pcts
        list so that volatility is computed across the full interleaved sequence.
    """
    fen_before = board.fen()
    move_san = board.san(move)
    is_cap_or_sac = see_capture_or_sacrifice(board, move)

    info_before = engine.analyse(board, limit, multipv=3)
    eval_before_white = white_cp(info_before[0]["score"])
    mover_eval_before = mover_cp(eval_before_white, mover)
    mover_win_pct_before = win_pct(mover_eval_before)
    gap = second_best_gap(info_before, mover_eval_before, mover)

    best_pv = info_before[0].get("pv") or []
    best_move_san = board.san(best_pv[0]) if best_pv else ""

    arrows, arrow_scores, pv_sans = _extract_arrows_and_pvs(info_before, board, mover)

    matched_idx: Optional[int] = None
    for pv_idx, pv_info in enumerate(info_before[:3]):
        pv = pv_info.get("pv") or []
        if pv and pv[0] == move:
            matched_idx = pv_idx
            break

    board.push(move)

    if matched_idx is not None:
        # Fast path: the engine already evaluated this move while building
        # the top-3 PV result above. The matched entry's `score` represents
        # the value of *playing* that move (mover POV), which is exactly
        # what a post-push analyse() would return — no second call needed.
        score_after = info_before[matched_idx]["score"]
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
    eval_after_white = white_cp(score_after)
    mover_win_pct_after = win_pct(mover_cp(eval_after_white, mover))
    # White-frame Win% after this ply — used in the game-wide all_win_pcts list.
    win_pct_after_white = win_pct(eval_after_white)

    cpl = total_cpl(info_before, score_after, eval_before_white, eval_after_white, mover)
    move_acc = move_accuracy(mover_win_pct_before, mover_win_pct_after)
    classification = classify_stockfish_move(
        cpl=cpl,
        second_best_gap=gap,
        mover_win_pct=mover_win_pct_before,
        is_capture_or_sacrifice=is_cap_or_sac,
    )

    move_result = _build_move_result(
        san=move_san,
        fen_before=fen_before,
        cp_eval_after_white=eval_after_white,
        cpl=cpl,
        best_move_san=best_move_san,
        classification=classification,
        arrows=arrows,
        arrow_scores=arrow_scores,
        pv_sans=pv_sans,
    )
    return move_result, move_acc, mover_win_pct_before, cpl, win_pct_after_white


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 4,
    hash_mb: int = 512,
    syzygy_path: str = "",
    progress_callback: Optional[Callable[..., None]] = None,
) -> StockfishGameResult:
    """Analyse a PGN game with Stockfish per analysis-math.md.

    Args:
        pgn_text: Full PGN string for the game.
        stockfish_path: Absolute path to the Stockfish binary.
        depth: Analysis depth (default 20).
        threads: Engine thread count (default 4).
        hash_mb: Engine hash table size in MB (default 512).
        syzygy_path: Path to Syzygy tablebase directory, or empty string.
        progress_callback: Optional callable(ply, total_plies) called per move.

    Returns:
        StockfishGameResult containing per-move evaluations, per-player
        accuracy/ACPL, and classification counts.
    """
    parsed = chess.pgn.read_game(io.StringIO(pgn_text))
    if parsed is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(parsed.mainline_moves())
    total_plies = len(moves_list)

    if total_plies == 0:
        # Refuse to submit empty analysis — completing a 0-ply game writes a
        # bogus row with all-zero accuracies/counts. Caller (run_one_job) will
        # catch this and call client.fail() so the job is surfaced.
        raise ValueError("PGN has no moves — cannot analyse a 0-ply game")

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    try:
        # MultiPV is passed directly to each analyse() call — do not set it
        # here as python-chess treats it as a managed option and will raise.
        opts: dict = {"Threads": threads, "Hash": hash_mb}
        if syzygy_path:
            opts["SyzygyPath"] = syzygy_path
        engine.configure(opts)

        board = parsed.board()
        move_results: list[StockfishMoveResult] = []

        white_accs: list[float] = []
        white_ply_indices: list[int] = []
        white_cpls: list[int] = []
        black_accs: list[float] = []
        black_ply_indices: list[int] = []
        black_cpls: list[int] = []

        # Game-wide White-frame Win% sequence — index 0 = initial position eval.
        # After each ply i the White-frame Win% is appended at index i.
        # Length = num_plies + 1 (mirrors Lichess allWinPercents).
        initial_info = engine.analyse(board, chess.engine.Limit(depth=depth))
        initial_eval_white = white_cp(initial_info["score"])
        all_win_pcts_game: list[float] = [win_pct(initial_eval_white)]

        cls_counts: dict = {
            chess.WHITE: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
            chess.BLACK: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
        }
        limit = chess.engine.Limit(depth=depth)

        for ply_index, move in enumerate(moves_list, start=1):
            mover = board.turn
            ply_started = time.monotonic()
            move_result, move_acc, mover_win_pct_before, cpl, wp_after_white = (
                _analyze_one_move(board, move, mover, engine, limit)
            )
            ply_seconds = time.monotonic() - ply_started
            move_result.ply = ply_index
            move_results.append(move_result)

            # Append White-frame Win% after this ply to the game-wide list.
            all_win_pcts_game.append(wp_after_white)

            if mover == chess.WHITE:
                white_accs.append(move_acc)
                white_ply_indices.append(ply_index)
                white_cpls.append(cpl)
            else:
                black_accs.append(move_acc)
                black_ply_indices.append(ply_index)
                black_cpls.append(cpl)

            if move_result.classification in cls_counts[mover]:
                cls_counts[mover][move_result.classification] += 1

            if progress_callback:
                # Pass move SAN + post-move FEN so the CLI can show which move
                # just finished and render the resulting board. depth/seconds
                # feed the issue-#44 per-ply readouts.
                progress_callback(
                    ply_index, total_plies, move_result.san, board.fen(),
                    depth=depth, seconds=ply_seconds,
                )

        def _avg(nums: list) -> float:
            """Return the arithmetic mean of a list, or 0.0 for empty lists."""
            return float(sum(nums)) / len(nums) if nums else 0.0

        return StockfishGameResult(
            engine_depth=depth,
            white_accuracy=game_accuracy(
                white_accs,
                all_win_pcts=all_win_pcts_game,
                mover_ply_indices=white_ply_indices,
            ),
            black_accuracy=game_accuracy(
                black_accs,
                all_win_pcts=all_win_pcts_game,
                mover_ply_indices=black_ply_indices,
            ),
            white_acpl=_avg(white_cpls),
            black_acpl=_avg(black_cpls),
            white_blunders=cls_counts[chess.WHITE]["Blunder"],
            white_mistakes=cls_counts[chess.WHITE]["Mistake"],
            white_inaccuracies=cls_counts[chess.WHITE]["Inaccuracy"],
            black_blunders=cls_counts[chess.BLACK]["Blunder"],
            black_mistakes=cls_counts[chess.BLACK]["Mistake"],
            black_inaccuracies=cls_counts[chess.BLACK]["Inaccuracy"],
            moves=move_results,
        )
    finally:
        engine.quit()


def build_stockfish_payload(result: StockfishGameResult, *, worker_id: str) -> dict:
    """Serialize a StockfishGameResult into the API complete payload dict.

    Args:
        result: StockfishGameResult from analyze_pgn().
        worker_id: Worker identifier string to include in the payload.

    Returns:
        Dict matching the StockfishCompleteSerializer schema.
    """
    return {
        "engine": "stockfish",
        "worker_id": worker_id,
        "engine_depth": result.engine_depth,
        "white_accuracy": result.white_accuracy,
        "black_accuracy": result.black_accuracy,
        "white_acpl": result.white_acpl,
        "black_acpl": result.black_acpl,
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
                "cp_eval": m.cp_eval,
                "cpl": m.cpl,
                "best_move": m.best_move,
                "classification": m.classification,
                "arrow_uci": m.arrow_uci,
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
