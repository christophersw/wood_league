"""
Title: analysis_service.py — Game analysis reconstruction service
Description:
    Retrieves complete game analysis from database combining Stockfish and Lc0 evaluations.
    Reconstructs move sequences from PGN when Stockfish analysis unavailable. Returns
    GameAnalysisData objects with move DataFrames, accuracy metrics, WDL probabilities,
    and opening information for UI rendering.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-08: Refactored get_game_analysis — extracted _load_db_game_records and _build_pgn_fallback_moves helpers
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import chess.pgn
import pandas as pd
from sqlalchemy import select

from wood_league_shared.services.opening_book import matched_opening_from_pgn
from app.storage.database import get_session, init_db
from app.storage.models import (
    Game,
    GameAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    MoveAnalysis,
)


@dataclass
class GameAnalysisData:
    """Container for complete game analysis including moves, ratings, and engine evaluations."""
    game_id: str
    white: str
    black: str
    result: str
    pgn: str
    moves: pd.DataFrame
    date: str = ""
    time_control: str = ""
    url: str = ""
    # Stockfish stats (None when not yet analyzed)
    white_accuracy: float | None = None
    black_accuracy: float | None = None
    white_acpl: float | None = None
    black_acpl: float | None = None
    white_blunders: int | None = None
    white_mistakes: int | None = None
    white_inaccuracies: int | None = None
    black_blunders: int | None = None
    black_mistakes: int | None = None
    black_inaccuracies: int | None = None
    engine_depth: int | None = None
    white_rating: int | None = None
    black_rating: int | None = None
    # Lc0 WDL data (None when not yet analyzed by Lc0)
    lc0_moves: pd.DataFrame | None = None
    lc0_white_win_prob: float | None = None
    lc0_white_draw_prob: float | None = None
    lc0_white_loss_prob: float | None = None
    lc0_black_win_prob: float | None = None
    lc0_black_draw_prob: float | None = None
    lc0_black_loss_prob: float | None = None
    lc0_white_blunders: int | None = None
    lc0_white_mistakes: int | None = None
    lc0_white_inaccuracies: int | None = None
    lc0_black_blunders: int | None = None
    lc0_black_mistakes: int | None = None
    lc0_black_inaccuracies: int | None = None
    lc0_engine_nodes: int | None = None
    lc0_network_name: str | None = None
    eco_code: str = ""
    opening_name: str = ""
    lichess_opening: str | None = None
    opening_id: int | None = None


def _load_db_game_records(session, game_id: str) -> dict | None:
    """Load Game, GameAnalysis, and Lc0GameAnalysis rows plus derived metadata for a game.

    Args:
        session: Active SQLAlchemy session.
        game_id: Game primary key.

    Returns:
        Dict with keys: db_game, game (parsed chess.pgn.Game), pgn_text, white, black,
        result, date, time_control, url, ga (GameAnalysis or None), lc0_moves_df,
        lc0_kwargs, eco_code, opening_name, lichess_opening, opening_id.
        Returns None if the game is not found or PGN cannot be parsed.
    """
    db_game = session.get(Game, game_id)
    if db_game is None:
        return None

    pgn_text = db_game.pgn or ""
    date = ""
    time_control = db_game.time_control or ""
    if db_game.played_at:
        date = db_game.played_at.strftime("%Y-%m-%d %H:%M")

    game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None
    if game is None:
        return None

    white = db_game.white_username or game.headers.get("White", "White")
    black = db_game.black_username or game.headers.get("Black", "Black")
    result = db_game.result_pgn or game.headers.get("Result", "*")
    if not date:
        date = game.headers.get("Date", "")
    if not time_control:
        time_control = game.headers.get("TimeControl", "")
    url = game.headers.get("Link", "")

    ga = session.execute(
        select(GameAnalysis).where(GameAnalysis.game_id == game_id)
    ).scalar_one_or_none()

    lga = session.execute(
        select(Lc0GameAnalysis).where(Lc0GameAnalysis.game_id == game_id)
    ).scalar_one_or_none()

    lc0_moves_df: pd.DataFrame | None = None
    if lga is not None and lga.analyzed_at is not None and lga.moves:
        lc0_moves_df = _lc0_moves_from_db(lga.moves)

    opening_match = matched_opening_from_pgn(pgn_text, max_ply=20)

    return {
        "db_game": db_game,
        "game": game,
        "pgn_text": pgn_text,
        "white": white,
        "black": black,
        "result": result,
        "date": date,
        "time_control": time_control,
        "url": url,
        "ga": ga,
        "lc0_moves_df": lc0_moves_df,
        "lc0_kwargs": _lc0_summary_kwargs(lga),
        "eco_code": db_game.eco_code or "",
        "opening_name": db_game.opening_name or "",
        "lichess_opening": db_game.lichess_opening,
        "opening_id": opening_match[0] if opening_match else None,
    }


def _build_pgn_fallback_moves(
    game: "chess.pgn.Game",
    lc0_by_ply: dict,
) -> pd.DataFrame:
    """Reconstruct a moves DataFrame from PGN, optionally annotating with Lc0 data.

    Args:
        game: Parsed chess.pgn.Game object.
        lc0_by_ply: Dict mapping ply (int) to a pandas Series row from the Lc0 moves DataFrame.

    Returns:
        DataFrame with columns: ply, san, fen, cp_eval, best_move, arrow_uci, cpl, base_severity, draw_character.
    """
    board = game.board()
    rows: list[dict] = []
    for ply, move in enumerate(game.mainline_moves(), start=1):
        san = board.san(move)
        board.push(move)
        lm = lc0_by_ply.get(ply)
        rows.append(
            {
                "ply": ply,
                "san": san,
                "fen": board.fen(),
                "cp_eval": float(lm["cp_equiv"]) if lm is not None else None,
                "best_move": str(lm["best_move"]) if lm is not None else "",
                "arrow_uci": str(lm["arrow_uci"]) if lm is not None else "",
                "cpl": None,
                # base_severity replaces old classification for Lc0 moves (#159)
                "base_severity": str(lm["base_severity"]) if lm is not None else None,
                "draw_character": str(lm["draw_character"]) if lm is not None and lm.get("draw_character") is not None else None,
            }
        )
    return pd.DataFrame(rows)


class AnalysisService:
    """Retrieves and reconstructs game analysis from database."""
    def __init__(self) -> None:
        """Initialize database."""
        init_db()

    def get_game_analysis(self, game_id: str) -> GameAnalysisData | None:
        """Load game analysis from database; reconstruct moves from PGN if Stockfish analysis unavailable."""
        if not game_id:
            return None

        with get_session() as session:
            rec = _load_db_game_records(session, game_id)
            if rec is None:
                return None

            ga = rec["ga"]
            lc0_moves_df = rec["lc0_moves_df"]

            # Stockfish path — full analysis available
            if ga is not None and ga.analyzed_at is not None and ga.moves:
                moves_df = _moves_from_db(ga.moves)
                return GameAnalysisData(
                    game_id=game_id,
                    white=rec["white"],
                    black=rec["black"],
                    result=rec["result"],
                    pgn=rec["pgn_text"],
                    moves=moves_df,
                    date=rec["date"],
                    time_control=rec["time_control"],
                    url=rec["url"],
                    white_accuracy=ga.white_accuracy,
                    black_accuracy=ga.black_accuracy,
                    white_acpl=ga.white_acpl,
                    black_acpl=ga.black_acpl,
                    white_blunders=ga.white_blunders,
                    white_mistakes=ga.white_mistakes,
                    white_inaccuracies=ga.white_inaccuracies,
                    black_blunders=ga.black_blunders,
                    black_mistakes=ga.black_mistakes,
                    black_inaccuracies=ga.black_inaccuracies,
                    engine_depth=ga.engine_depth,
                    white_rating=rec["db_game"].white_rating,
                    black_rating=rec["db_game"].black_rating,
                    lc0_moves=lc0_moves_df,
                    eco_code=rec["eco_code"],
                    opening_name=rec["opening_name"],
                    lichess_opening=rec["lichess_opening"],
                    opening_id=rec["opening_id"],
                    **rec["lc0_kwargs"],
                )

            # No Stockfish analysis — build Lc0-by-ply index before session closes
            lc0_by_ply: dict[int, pd.Series] = {}
            if lc0_moves_df is not None and not lc0_moves_df.empty:
                for _, row in lc0_moves_df.iterrows():
                    lc0_by_ply[int(row["ply"])] = row

        # PGN fallback — reconstruct move list from PGN, attach Lc0 where present
        moves_df = _build_pgn_fallback_moves(rec["game"], lc0_by_ply)
        return GameAnalysisData(
            game_id=game_id,
            white=rec["white"],
            black=rec["black"],
            result=rec["result"],
            pgn=rec["pgn_text"],
            moves=moves_df,
            date=rec["date"],
            time_control=rec["time_control"],
            url=rec["url"],
            white_rating=rec["db_game"].white_rating,
            black_rating=rec["db_game"].black_rating,
            lc0_moves=lc0_moves_df,
            eco_code=rec["eco_code"],
            opening_name=rec["opening_name"],
            lichess_opening=rec["lichess_opening"],
            opening_id=rec["opening_id"],
            **rec["lc0_kwargs"],
        )


def _lc0_summary_kwargs(lga: "Lc0GameAnalysis | None") -> dict:
    """Extract scalar Lc0 summary fields for GameAnalysisData kwargs."""
    if lga is None:
        return {
            "lc0_white_win_prob": None,
            "lc0_white_draw_prob": None,
            "lc0_white_loss_prob": None,
            "lc0_black_win_prob": None,
            "lc0_black_draw_prob": None,
            "lc0_black_loss_prob": None,
            "lc0_white_blunders": None,
            "lc0_white_mistakes": None,
            "lc0_white_inaccuracies": None,
            "lc0_black_blunders": None,
            "lc0_black_mistakes": None,
            "lc0_black_inaccuracies": None,
            "lc0_engine_nodes": None,
            "lc0_network_name": None,
        }
    return {
        "lc0_white_win_prob": lga.white_win_prob,
        "lc0_white_draw_prob": lga.white_draw_prob,
        "lc0_white_loss_prob": lga.white_loss_prob,
        "lc0_black_win_prob": lga.black_win_prob,
        "lc0_black_draw_prob": lga.black_draw_prob,
        "lc0_black_loss_prob": lga.black_loss_prob,
        "lc0_white_blunders": lga.white_blunders,
        "lc0_white_mistakes": lga.white_mistakes,
        "lc0_white_inaccuracies": lga.white_inaccuracies,
        "lc0_black_blunders": lga.black_blunders,
        "lc0_black_mistakes": lga.black_mistakes,
        "lc0_black_inaccuracies": lga.black_inaccuracies,
        "lc0_engine_nodes": lga.engine_nodes,
        "lc0_network_name": lga.network_name,
    }


def _lc0_moves_from_db(move_rows: list["Lc0MoveAnalysis"]) -> pd.DataFrame:
    """Convert Lc0 move analysis database records to DataFrame with sorted plies."""
    sorted_moves = sorted(move_rows, key=lambda m: m.ply)
    rows = [
        {
            "ply": m.ply,
            "san": m.san,
            "fen": m.fen,
            "wdl_win": m.wdl_win,
            "wdl_draw": m.wdl_draw,
            "wdl_loss": m.wdl_loss,
            # cp_equiv, arrow_score_*, move_win_delta gone from Lc0MoveAnalysis
            # in #161 Phase F. Keys preserved as None so downstream consumers
            # that read by name don't KeyError mid-cutover; populate from new
            # derived columns (wdl_mu / delta_mu / delta_d) in Phase G/J.
            "cp_equiv": None,
            "best_move": m.best_move,
            "arrow_uci": m.arrow_uci_1,
            "arrow_uci_2": m.arrow_uci_2 or "",
            "arrow_uci_3": m.arrow_uci_3 or "",
            "arrow_score_1": None,
            "arrow_score_2": None,
            "arrow_score_3": None,
            "move_win_delta": None,
            # base_severity + draw_character replace old classification (#159)
            "base_severity": m.base_severity,
            "draw_character": m.draw_character,
        }
        for m in sorted_moves
    ]
    return pd.DataFrame(rows)


def _moves_from_db(move_rows: list[MoveAnalysis]) -> pd.DataFrame:
    """Convert Stockfish move analysis database records to DataFrame with sorted plies."""
    sorted_moves = sorted(move_rows, key=lambda m: m.ply)
    rows = [
        {
            "ply": m.ply,
            "san": m.san,
            "fen": m.fen,
            "cp_eval": m.cp_eval,
            "mate_in": m.mate_in,
            "best_move": m.best_move,
            # ``arrow_uci_1`` (model) → ``arrow_uci`` (dict key) for templates.
            "arrow_uci": m.arrow_uci_1,
            "arrow_uci_2": m.arrow_uci_2 or "",
            "arrow_uci_3": m.arrow_uci_3 or "",
            "arrow_score_1": m.arrow_score_1,
            "arrow_score_2": m.arrow_score_2,
            "arrow_score_3": m.arrow_score_3,
            "cpl": m.cpl,
            "move_win_delta": m.move_win_delta,
            "classification": m.classification,
        }
        for m in sorted_moves
    ]
    return pd.DataFrame(rows)
