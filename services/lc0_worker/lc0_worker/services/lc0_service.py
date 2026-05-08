"""
Title: lc0_service.py — Leela Chess Zero (Lc0) analysis service
Description:
    Analyzes chess games using the Lc0 engine over UCI. Captures per-move
    WDL probabilities, derives move quality and classification, and extracts
    full SAN continuations for up to three multipv lines per position.

    Lc0 outputs native WDL (Win/Draw/Loss) probabilities in permille (0-1000, sum=1000)
    via UCI_ShowWDL=true. This service captures per-move WDL and derives:
        - Win probability for each side at each ply
        - Move quality (win% delta from the mover's perspective)
        - Move classification (brilliant/great/best/excellent/inaccuracy/mistake/blunder)
        - Q-equivalent centipawns via: cp = 111.71 * tan(1.56 * Q)
        - Game-level WDL summary (final position probabilities averaged over the game)

Changelog:
    2026-05-05 (#1): Extract and persist full PV continuations for all 3 multipv lines
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess
import chess.engine
import chess.pgn

_BLUNDER_WP_LOSS = 10.0
_MISTAKE_WP_LOSS = 5.0
_INACCURACY_WP_LOSS = 2.0

_BRILLIANT_MAX_LOSS = 1.0
_BRILLIANT_WIN_CEIL = 70.0
_BRILLIANT_ALT_DELTA = 10.0
_GREAT_MAX_LOSS = 1.0
_GREAT_ALT_DELTA = 6.0


@dataclass
class Lc0MoveResult:
    ply: int
    san: str
    fen: str
    wdl_win: int
    wdl_draw: int
    wdl_loss: int
    cp_equiv: float
    best_move: str
    arrow_uci: str
    arrow_uci_2: str = ""  # 2nd-best candidate UCI
    arrow_uci_3: str = ""  # 3rd-best candidate UCI
    arrow_score_1: float | None = None
    arrow_score_2: float | None = None
    arrow_score_3: float | None = None
    move_win_delta: float = 0.0
    classification: str = "best"
    pv_san_1: list[str] = field(default_factory=list)  # SAN continuation — best line
    pv_san_2: list[str] = field(default_factory=list)  # SAN continuation — 2nd-best line
    pv_san_3: list[str] = field(default_factory=list)  # SAN continuation — 3rd-best line


@dataclass
class Lc0PlayerStats:
    avg_win_prob: float
    avg_draw_prob: float
    avg_loss_prob: float
    blunders: int
    mistakes: int
    inaccuracies: int


@dataclass
class Lc0GameResult:
    white_stats: Lc0PlayerStats
    black_stats: Lc0PlayerStats
    moves: list[Lc0MoveResult]
    engine_nodes: int
    network_name: str
    analyzed_at: datetime


def _q_to_cp(q: float) -> float:
    q_clamped = max(-0.9999, min(0.9999, q))
    return 111.71 * math.tan(1.56 * q_clamped)


def _extract_wdl(info: chess.engine.InfoDict) -> tuple[int, int, int]:
    wdl = info.get("wdl")
    if wdl is not None:
        wdl_rel = wdl.relative if hasattr(wdl, "relative") else wdl
        w, d, l = int(wdl_rel.wins), int(wdl_rel.draws), int(wdl_rel.losses)
        total = w + d + l
        if total > 0 and total != 1000:
            w = round(w * 1000 / total)
            d = round(d * 1000 / total)
            l = 1000 - w - d
        return w, d, l

    score = info.get("score")
    if score is not None:
        q_val = score.relative.score(mate_score=10000) or 0
        q_norm = max(-9999, min(9999, q_val)) / 10000.0
        win_p = int(500 + 500 * q_norm)
        draw_p = max(0, 1000 - 2 * abs(win_p - 500))
        loss_p = 1000 - win_p - draw_p
        return win_p, draw_p, loss_p

    return 500, 0, 500


def _classify(
    win_delta: float,
    mover_win_pct_before: float,
    alt_win_delta: float | None,
    is_capture: bool,
) -> str:
    if win_delta >= _BLUNDER_WP_LOSS:
        return "blunder"
    if win_delta >= _MISTAKE_WP_LOSS:
        return "mistake"
    if win_delta >= _INACCURACY_WP_LOSS:
        return "inaccuracy"

    if (
        win_delta <= _BRILLIANT_MAX_LOSS
        and is_capture
        and mover_win_pct_before < _BRILLIANT_WIN_CEIL
        and alt_win_delta is not None
        and alt_win_delta >= _BRILLIANT_ALT_DELTA
    ):
        return "brilliant"

    if (
        win_delta <= _GREAT_MAX_LOSS
        and alt_win_delta is not None
        and alt_win_delta >= _GREAT_ALT_DELTA
    ):
        return "great"

    if win_delta <= _BRILLIANT_MAX_LOSS:
        return "best"
    return "excellent"


def _pv_to_san(board: chess.Board, pv: list) -> list[str]:
    """Convert a list of chess.Move objects to SAN notation strings.

    Walks the principal variation on a temporary board copy so the source
    position is never mutated. Stops early if a move is illegal on the
    running copy (should not happen with valid engine output, but guards
    against corrupt PV lists).

    Parameters:
        board: the position *before* the first move in pv is played.
        pv:    list of chess.Move objects returned by engine analysis.

    Returns:
        List of SAN strings for each move in pv, in order.
    """
    temp_board = board.copy()
    san_moves: list[str] = []
    for pv_move in pv:
        if not temp_board.is_legal(pv_move):
            break
        san_moves.append(temp_board.san(pv_move))
        temp_board.push(pv_move)
    return san_moves


def analyze_pgn(
    pgn_text: str,
    lc0_path: str,
    nodes: int = 25000,
    move_callback: "callable[[int, int, str], None] | None" = None,
    weights_path: str = "",
    syzygy_path: str = "",
    backend: str = "",
) -> Lc0GameResult:
    """Analyze a full PGN with Lc0 and return per-move WDL results."""
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Could not parse PGN")

    total_moves = sum(1 for _ in game.mainline_moves())
    limit = chess.engine.Limit(nodes=nodes)

    move_results: list[Lc0MoveResult] = []
    white_win_probs: list[float] = []
    white_draw_probs: list[float] = []
    white_loss_probs: list[float] = []
    black_win_probs: list[float] = []
    black_draw_probs: list[float] = []
    black_loss_probs: list[float] = []
    white_deltas: list[float] = []
    black_deltas: list[float] = []

    cmd = [lc0_path]
    if backend:
        cmd.append(f"--backend={backend}")

    with chess.engine.SimpleEngine.popen_uci(cmd) as engine:
        config: dict[str, str] = {"UCI_ShowWDL": "true"}
        if weights_path:
            config["WeightsFile"] = weights_path
        if syzygy_path:
            config["SyzygyPath"] = syzygy_path
        engine.configure(config)

        board = game.board()
        for node in game.mainline():
            move = node.move
            ply = board.ply() + 1
            is_white_move = board.turn == chess.WHITE

            if board.is_game_over() or not any(True for _ in board.legal_moves):
                board.push(move)
                continue

            san = board.san(move)
            is_capture = board.is_capture(move)

            pre_results = engine.analyse(board, limit, multipv=3)
            if isinstance(pre_results, list):
                pre_top = pre_results[0]
                pre_alt = pre_results[1] if len(pre_results) > 1 else None
                pre_third = pre_results[2] if len(pre_results) > 2 else None
            else:
                pre_top = pre_results
                pre_alt = None
                pre_third = None

            pre_w, pre_d, pre_l = _extract_wdl(pre_top)
            mover_win_before = pre_w / 10.0
            pre_q = (pre_w - pre_l) / 1000.0
            score_1 = _q_to_cp(pre_q)
            score_2: float | None = None
            score_3: float | None = None
            if pre_alt is not None:
                alt_w, _, alt_l = _extract_wdl(pre_alt)
                score_2 = _q_to_cp((alt_w - alt_l) / 1000.0)
            if pre_third is not None:
                third_w, _, third_l = _extract_wdl(pre_third)
                score_3 = _q_to_cp((third_w - third_l) / 1000.0)

            best_move_obj = pre_top.get("pv", [None])[0]
            best_move_str = best_move_obj.uci() if best_move_obj else ""

            second_move_obj = (
                pre_alt.get("pv", [None])[0] if pre_alt is not None else None
            )
            third_move_obj = (
                pre_third.get("pv", [None])[0] if pre_third is not None else None
            )
            second_move_str = second_move_obj.uci() if second_move_obj else ""
            third_move_str = third_move_obj.uci() if third_move_obj else ""

            # Full SAN continuations for each multipv line (board not yet pushed).
            pv_san_1 = _pv_to_san(board, pre_top.get("pv", []))
            pv_san_2 = _pv_to_san(board, pre_alt.get("pv", [])) if pre_alt is not None else []
            pv_san_3 = _pv_to_san(board, pre_third.get("pv", [])) if pre_third is not None else []

            alt_win_delta: float | None = None
            if pre_alt is not None:
                alt_w, _, _ = _extract_wdl(pre_alt)
                alt_win_pct = alt_w / 10.0
                alt_win_delta = mover_win_before - alt_win_pct

            board.push(move)
            if board.is_game_over():
                outcome = board.outcome()
                if outcome is not None and outcome.winner is not None:
                    post_w, post_d, post_l = 0, 0, 1000
                else:
                    post_w, post_d, post_l = 0, 1000, 0
                post_score = None
            else:
                post_info = engine.analyse(board, limit)
                post_w, post_d, post_l = _extract_wdl(post_info)
                post_score = post_info.get("score")

            mover_win_after = post_l / 10.0
            win_delta = max(0.0, mover_win_before - mover_win_after)

            classification = _classify(
                win_delta=win_delta,
                mover_win_pct_before=mover_win_before,
                alt_win_delta=alt_win_delta,
                is_capture=is_capture,
            )

            if post_score is not None:
                white_score = post_score.white()
                raw = white_score.score(mate_score=10000) or 0
                cp_eq = _q_to_cp(max(-9999, min(9999, raw)) / 10000.0)
            else:
                q_approx = (post_w - post_l) / 1000.0
                if not is_white_move:
                    q_approx = -q_approx
                cp_eq = _q_to_cp(q_approx)

            if is_white_move:
                stored_win = pre_w
                stored_draw = pre_d
                stored_loss = pre_l
            else:
                stored_win = pre_l
                stored_draw = pre_d
                stored_loss = pre_w

            if is_white_move:
                w_win_after = post_l / 10.0
                w_draw_after = post_d / 10.0
                w_loss_after = post_w / 10.0
                white_win_probs.append(w_win_after)
                white_draw_probs.append(w_draw_after)
                white_loss_probs.append(w_loss_after)
                white_deltas.append(win_delta)
            else:
                b_win_after = post_l / 10.0
                b_draw_after = post_d / 10.0
                b_loss_after = post_w / 10.0
                black_win_probs.append(b_win_after)
                black_draw_probs.append(b_draw_after)
                black_loss_probs.append(b_loss_after)
                black_deltas.append(win_delta)

            move_results.append(
                Lc0MoveResult(
                    ply=ply,
                    san=san,
                    fen=board.fen(),
                    wdl_win=stored_win,
                    wdl_draw=stored_draw,
                    wdl_loss=stored_loss,
                    cp_equiv=cp_eq,
                    best_move=best_move_str,
                    arrow_uci=best_move_str,
                    arrow_uci_2=second_move_str,
                    arrow_uci_3=third_move_str,
                    arrow_score_1=score_1,
                    arrow_score_2=score_2,
                    arrow_score_3=score_3,
                    move_win_delta=win_delta,
                    classification=classification,
                    pv_san_1=pv_san_1,
                    pv_san_2=pv_san_2,
                    pv_san_3=pv_san_3,
                )
            )

            if move_callback:
                move_callback(ply, total_moves, san)

    def _player_stats(
        win_probs: list[float],
        draw_probs: list[float],
        loss_probs: list[float],
        deltas: list[float],
    ) -> Lc0PlayerStats:
        if not deltas:
            return Lc0PlayerStats(
                avg_win_prob=50.0,
                avg_draw_prob=0.0,
                avg_loss_prob=50.0,
                blunders=0,
                mistakes=0,
                inaccuracies=0,
            )
        return Lc0PlayerStats(
            avg_win_prob=sum(win_probs) / len(win_probs),
            avg_draw_prob=sum(draw_probs) / len(draw_probs),
            avg_loss_prob=sum(loss_probs) / len(loss_probs),
            blunders=sum(1 for d in deltas if d >= _BLUNDER_WP_LOSS),
            mistakes=sum(1 for d in deltas if _MISTAKE_WP_LOSS <= d < _BLUNDER_WP_LOSS),
            inaccuracies=sum(
                1 for d in deltas if _INACCURACY_WP_LOSS <= d < _MISTAKE_WP_LOSS
            ),
        )

    network_name = ""
    try:
        with chess.engine.SimpleEngine.popen_uci(lc0_path) as eng:
            network_name = eng.id.get("name", "")
    except Exception:
        pass

    return Lc0GameResult(
        white_stats=_player_stats(
            white_win_probs, white_draw_probs, white_loss_probs, white_deltas
        ),
        black_stats=_player_stats(
            black_win_probs, black_draw_probs, black_loss_probs, black_deltas
        ),
        moves=move_results,
        engine_nodes=nodes,
        network_name=network_name,
        analyzed_at=datetime.now(timezone.utc),
    )
