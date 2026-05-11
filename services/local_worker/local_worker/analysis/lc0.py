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
"""
from __future__ import annotations

import io
import json
import logging
from typing import Callable, Optional

import chess
import chess.engine
import chess.pgn

from .math import classify_lc0_move, cp_equiv_from_q
from .models import Lc0MoveResult, Lc0GameResult
from .see import see_capture_or_sacrifice

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
            for pv_move in pv[:5]:
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


def _analyze_one_move(
    board: chess.Board,
    move: chess.Move,
    ply_index: int,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
) -> tuple[Lc0MoveResult, chess.Color, tuple[int, int, int]]:
    """Analyse a single move: evaluate before/after, classify, and build result.

    Pushes `move` onto `board` in place.

    Args:
        board: Board before the move (mutated — move is pushed at the end).
        move: The move to analyse.
        ply_index: 1-based ply number (1 = White's first move).
        engine: Running Lc0 engine instance.
        limit: Node/depth limit for analysis.

    Returns:
        Tuple of (Lc0MoveResult, mover_color, wdl_white_after) where
        wdl_white_after is (win, draw, loss) in White's frame after the move.
    """
    mover = board.turn
    fen_before = board.fen()
    move_san = board.san(move)
    is_cap_or_sac = see_capture_or_sacrifice(board, move)

    log.debug("lc0: analyse() multipv=3 starting")
    info_before_list = engine.analyse(board, limit, multipv=3)
    log.debug("lc0: analyse() multipv=3 returned")
    wdl_before = info_before_list[0]["score"].pov(mover).wdl()
    mover_win_pct_before = _mover_win_pct_from_wdl(wdl_before)

    arrows, arrow_scores, pv_sans = _analyze_arrows(info_before_list, board, mover)
    second_best_gap = _second_best_gap_from_scores(arrow_scores)

    best_move_uci = arrows[0] if arrows else ""
    best_move_san = board.san(chess.Move.from_uci(best_move_uci)) if best_move_uci else ""

    board.push(move)

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


def analyze_pgn(
    pgn_text: str,
    lc0_path: str,
    nodes: int = 10000,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "cpu",
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
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

    Returns:
        Lc0GameResult with per-move WDL evaluations and game statistics.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Failed to parse PGN")

    moves_list = list(game.mainline_moves())
    total_plies = len(moves_list)
    network_name = ""

    log.info("lc0: launching engine at %s", lc0_path)
    engine = chess.engine.SimpleEngine.popen_uci(lc0_path)
    log.info("lc0: engine launched; configuring backend=%s weights=%s syzygy=%s",
             backend or "(default)", weights_path or "(default)", syzygy_path or "(none)")
    try:
        opts: dict[str, str] = {}
        if backend:
            opts["Backend"] = backend
        if weights_path:
            opts["WeightsFile"] = weights_path
        if syzygy_path:
            opts["SyzygyPath"] = syzygy_path
        if opts:
            engine.configure(opts)
            log.info("lc0: configure complete")

        try:
            engine_id_name = engine.id.get("name", "")
            network_name = _parse_network_name(engine_id_name, weights_path)
        except Exception:
            pass

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
        log.info("lc0: entering move loop — %d plies, %d nodes/move", total_plies, nodes)

        for ply_index, move in enumerate(moves_list, start=1):
            log.info("lc0: analysing ply %d/%d", ply_index, total_plies)
            move_result, mover, wdl_white = _analyze_one_move(
                board, move, ply_index, engine, limit
            )
            move_results.append(move_result)

            side = "white" if mover == chess.WHITE else "black"
            if move_result.classification in cls_counts[side]:
                cls_counts[side][move_result.classification] += 1

            if mover == chess.WHITE:
                white_wdl_wins.append(wdl_white[0] / 1000)
                white_wdl_draws.append(wdl_white[1] / 1000)
                white_wdl_losses.append(wdl_white[2] / 1000)
            else:
                black_wdl_wins.append(wdl_white[0] / 1000)
                black_wdl_draws.append(wdl_white[1] / 1000)
                black_wdl_losses.append(wdl_white[2] / 1000)

            if progress_callback:
                # Pass move SAN + post-move FEN so the CLI can show which move
                # just finished and render the resulting board.
                progress_callback(ply_index, total_plies, move_result.san, board.fen())

        def _avg(lst: list[float]) -> float:
            """Return average of a list, or 0.0 if empty."""
            return sum(lst) / len(lst) if lst else 0.0

        return Lc0GameResult(
            engine_nodes=nodes,
            network_name=network_name,
            white_win_prob=_avg(white_wdl_wins),
            white_draw_prob=_avg(white_wdl_draws),
            white_loss_prob=_avg(white_wdl_losses),
            black_win_prob=_avg(black_wdl_wins),
            black_draw_prob=_avg(black_wdl_draws),
            black_loss_prob=_avg(black_wdl_losses),
            white_blunders=cls_counts["white"]["Blunder"],
            white_mistakes=cls_counts["white"]["Mistake"],
            white_inaccuracies=cls_counts["white"]["Inaccuracy"],
            black_blunders=cls_counts["black"]["Blunder"],
            black_mistakes=cls_counts["black"]["Mistake"],
            black_inaccuracies=cls_counts["black"]["Inaccuracy"],
            moves=move_results,
        )
    finally:
        engine.quit()


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
