"""
Title: stockfish.py — Stockfish UCI analysis engine
Description:
    Runs Stockfish analysis on a PGN string via the python-chess UCI interface.
    Produces a StockfishGameResult with per-move evaluations and classifications
    that conform exactly to services/app/documentation/analysis-math.md:
      - cp values are stored from White's frame; mover-perspective is derived
        via cpl_from_evals() and pov(mover).
      - Capture/sacrifice detection uses SEE (analysis/see.py).
      - Game accuracy uses windowed Win%-stddev weighting plus harmonic mean.
      - ACPL is per-player.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import io
import logging
from typing import Callable, Optional

import chess
import chess.engine
import chess.pgn

from ._stockfish_helpers import mover_cp, second_best_gap, total_cpl, white_cp
from .math import classify_stockfish_move, game_accuracy, move_accuracy, win_pct
from .models import StockfishGameResult, StockfishMoveResult
from .see import see_capture_or_sacrifice

log = logging.getLogger(__name__)


def _analyze_one_move(
    board: chess.Board,
    move: chess.Move,
    mover: chess.Color,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
) -> tuple[StockfishMoveResult, float, float, int]:
    """Analyse a single move and return results plus per-player accumulator values.

    Captures the SAN and SEE result before pushing the move, then analyses
    both the before and after positions with the engine.

    Args:
        board: Position before the move (will be mutated by push).
        move: The move to analyse.
        mover: The colour making the move.
        engine: Configured Stockfish engine instance.
        limit: Engine search limit (depth/time/nodes).

    Returns:
        Tuple of (StockfishMoveResult, move_acc, mover_win_pct_before, cpl).
        The caller is responsible for appending these to the per-player lists.
    """
    fen_before = board.fen()
    move_san = board.san(move)
    is_cap_or_sac = see_capture_or_sacrifice(board, move)

    info_before = engine.analyse(board, limit, multipv=2)
    eval_before_white = white_cp(info_before[0]["score"])
    mover_eval_before = mover_cp(eval_before_white, mover)
    mover_win_pct_before = win_pct(mover_eval_before)
    gap = second_best_gap(info_before, mover_eval_before, mover)

    best_pv = info_before[0].get("pv") or []
    best_move_san = board.san(best_pv[0]) if best_pv else ""

    board.push(move)
    info_after = engine.analyse(board, limit)
    eval_after_white = white_cp(info_after["score"])
    mover_win_pct_after = win_pct(mover_cp(eval_after_white, mover))

    cpl = total_cpl(info_before, info_after, eval_before_white, eval_after_white, mover)
    move_acc = move_accuracy(mover_win_pct_before, mover_win_pct_after)
    classification = classify_stockfish_move(
        cpl=cpl,
        second_best_gap=gap,
        mover_win_pct=mover_win_pct_before,
        is_capture_or_sacrifice=is_cap_or_sac,
    )

    move_result = StockfishMoveResult(
        ply=0,  # caller sets ply_index
        san=move_san,
        fen=fen_before,
        cp_eval=eval_after_white,
        cpl=cpl,
        best_move=best_move_san,
        classification=classification,
    )
    return move_result, move_acc, mover_win_pct_before, cpl


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 4,
    hash_mb: int = 512,
    syzygy_path: str = "",
    progress_callback: Optional[Callable[[int, int], None]] = None,
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

    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    try:
        opts: dict = {"Threads": threads, "Hash": hash_mb, "MultiPV": 2}
        if syzygy_path:
            opts["SyzygyPath"] = syzygy_path
        engine.configure(opts)

        board = parsed.board()
        move_results: list[StockfishMoveResult] = []

        white_accs: list[float] = []
        white_winpcts_before: list[float] = []
        white_cpls: list[int] = []
        black_accs: list[float] = []
        black_winpcts_before: list[float] = []
        black_cpls: list[int] = []

        cls_counts: dict = {
            chess.WHITE: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
            chess.BLACK: {"Blunder": 0, "Mistake": 0, "Inaccuracy": 0},
        }
        limit = chess.engine.Limit(depth=depth)

        for ply_index, move in enumerate(moves_list, start=1):
            mover = board.turn
            move_result, move_acc, mover_win_pct_before, cpl = _analyze_one_move(
                board, move, mover, engine, limit
            )
            move_result.ply = ply_index
            move_results.append(move_result)

            if mover == chess.WHITE:
                white_accs.append(move_acc)
                white_winpcts_before.append(mover_win_pct_before)
                white_cpls.append(cpl)
            else:
                black_accs.append(move_acc)
                black_winpcts_before.append(mover_win_pct_before)
                black_cpls.append(cpl)

            if move_result.classification in cls_counts[mover]:
                cls_counts[mover][move_result.classification] += 1

            if progress_callback:
                progress_callback(ply_index, total_plies)

        def _avg(nums: list) -> float:
            """Return the arithmetic mean of a list, or 0.0 for empty lists."""
            return float(sum(nums)) / len(nums) if nums else 0.0

        return StockfishGameResult(
            engine_depth=depth,
            white_accuracy=game_accuracy(white_accs, win_pcts=white_winpcts_before),
            black_accuracy=game_accuracy(black_accs, win_pcts=black_winpcts_before),
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
            }
            for m in result.moves
        ],
    }
