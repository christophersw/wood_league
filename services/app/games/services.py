"""
Title: services.py — Game analysis data assembly service
Description:
    Loads and assembles complete game analysis data from Stockfish and Lc0
    database records into a single GameAnalysisData dataclass for use by
    views and template rendering utilities.

Changelog:
    2026-05-04 (#16): Added opening_id field for linking to opening detail page
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import chess.pgn

from analysis.models import GameAnalysis, Lc0GameAnalysis
from games.models import Game
from openings.models import OpeningBook


@dataclass
class MoveRow:
    """Container for a single move's analysis from engine evaluation."""
    ply: int
    san: str
    fen: str
    cp_eval: float | None = None
    cpl: float | None = None
    best_move: str = ""
    arrow_uci: str = ""
    arrow_uci_2: str = ""
    arrow_uci_3: str = ""
    arrow_score_1: float | None = None
    arrow_score_2: float | None = None
    arrow_score_3: float | None = None
    classification: str | None = None
    wdl_win: int | None = None
    wdl_draw: int | None = None
    wdl_loss: int | None = None
    cp_equiv: float | None = None
    move_win_delta: float | None = None
    pv_san_1: str | None = None
    pv_san_2: str | None = None
    pv_san_3: str | None = None


@dataclass
class GameAnalysisData:
    """Complete game analysis data aggregated from Stockfish and Lc0 analysis."""

    game_id: str
    white: str
    black: str
    result: str
    pgn: str
    moves: list[MoveRow] = field(default_factory=list)
    date: str = ""
    time_control: str = ""
    url: str = ""
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
    lc0_moves: list[MoveRow] | None = None
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

    @property
    def has_sf(self) -> bool:
        """True if Stockfish analysis is available."""
        return self.white_accuracy is not None or self.white_acpl is not None

    @property
    def has_lc0(self) -> bool:
        """True if Lc0 neural network analysis is available."""
        return self.lc0_moves is not None and len(self.lc0_moves) > 0

    @property
    def white_label(self) -> str:
        """Return white player name with rating if available."""
        if self.white_rating:
            return f"{self.white} ({self.white_rating})"
        return self.white

    @property
    def black_label(self) -> str:
        """Return black player name with rating if available."""
        if self.black_rating:
            return f"{self.black} ({self.black_rating})"
        return self.black


def get_game_analysis(slug: str) -> GameAnalysisData | None:
    """Load and assemble game analysis from Stockfish and Lc0 sources, or None if not found."""
    try:
        db_game = Game.objects.select_related().get(slug=slug)
    except Game.DoesNotExist:
        return None

    pgn_text = db_game.pgn or ""
    game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None
    if game is None:
        return None

    white = db_game.white_username or game.headers.get("White", "White")
    black = db_game.black_username or game.headers.get("Black", "Black")
    result = db_game.result_pgn or game.headers.get("Result", "*")
    date = ""
    time_control = db_game.time_control or game.headers.get("TimeControl", "")
    url = game.headers.get("Link", "")
    if db_game.played_at:
        date = db_game.played_at.strftime("%Y-%m-%d %H:%M")
    if not date:
        date = game.headers.get("Date", "")

    eco_code = db_game.eco_code or ""
    opening_name = db_game.opening_name or ""

    opening_id = None
    if eco_code:
        opening_id = OpeningBook.objects.filter(eco=eco_code).values_list("id", flat=True).first()

    lga = _load_lc0(db_game)
    lc0_moves = _lc0_move_rows(lga)
    lc0_kwargs = _lc0_summary_kwargs(lga)

    ga = _load_sf(db_game)

    if ga is not None and ga.analyzed_at is not None:
        sf_moves = [
            MoveRow(
                ply=m.ply,
                san=m.san,
                fen=m.fen,
                cp_eval=m.cp_eval,
                cpl=m.cpl,
                best_move=m.best_move or "",
                arrow_uci=m.arrow_uci or "",
                arrow_uci_2=m.arrow_uci_2 or "",
                arrow_uci_3=m.arrow_uci_3 or "",
                arrow_score_1=m.arrow_score_1,
                arrow_score_2=m.arrow_score_2,
                arrow_score_3=m.arrow_score_3,
                classification=m.classification,
                pv_san_1=m.pv_san_1,
                pv_san_2=m.pv_san_2,
                pv_san_3=m.pv_san_3,
            )
            for m in ga.moves.order_by("ply")
        ]
        return GameAnalysisData(
            game_id=db_game.id,
            white=white,
            black=black,
            result=result,
            pgn=pgn_text,
            moves=sf_moves,
            date=date,
            time_control=time_control,
            url=url,
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
            white_rating=db_game.white_rating,
            black_rating=db_game.black_rating,
            lc0_moves=lc0_moves,
            eco_code=eco_code,
            opening_name=opening_name,
            lichess_opening=db_game.lichess_opening,
            opening_id=opening_id,
            **lc0_kwargs,
        )

    # No Stockfish — build move list from PGN, attach Lc0 cp_equiv as proxy
    lc0_by_ply: dict[int, MoveRow] = {r.ply: r for r in lc0_moves} if lc0_moves else {}

    board = game.board()
    start_offset = board.ply()
    pgn_moves: list[MoveRow] = []
    for ply_i, move in enumerate(game.mainline_moves(), start=1):
        san = board.san(move)
        board.push(move)
        abs_ply = ply_i + start_offset
        lm = lc0_by_ply.get(abs_ply) or lc0_by_ply.get(ply_i)
        pgn_moves.append(
            MoveRow(
                ply=abs_ply,
                san=san,
                fen=board.fen(),
                cp_eval=float(lm.cp_equiv) if lm and lm.cp_equiv is not None else None,
                best_move=lm.best_move if lm else "",
                arrow_uci=lm.arrow_uci if lm else "",
                classification=lm.classification if lm else None,
                pv_san_1=lm.pv_san_1 if lm else None,
                pv_san_2=lm.pv_san_2 if lm else None,
                pv_san_3=lm.pv_san_3 if lm else None,
            )
        )

    return GameAnalysisData(
        game_id=db_game.id,
        white=white,
        black=black,
        result=result,
        pgn=pgn_text,
        moves=pgn_moves,
        date=date,
        time_control=time_control,
        url=url,
        white_rating=db_game.white_rating,
        black_rating=db_game.black_rating,
        lc0_moves=lc0_moves,
        eco_code=eco_code,
        opening_name=opening_name,
        lichess_opening=db_game.lichess_opening,
        opening_id=opening_id,
        **lc0_kwargs,
    )


def _load_sf(db_game: Game) -> GameAnalysis | None:
    """Load Stockfish analysis for a game or return None if not analyzed."""
    try:
        return db_game.analysis
    except GameAnalysis.DoesNotExist:
        return None


def _load_lc0(db_game: Game) -> Lc0GameAnalysis | None:
    """Load Lc0 analysis for a game or return None if not analyzed."""
    try:
        lga = db_game.lc0_analysis
        if lga.analyzed_at is None:
            return None
        return lga
    except Lc0GameAnalysis.DoesNotExist:
        return None


def _lc0_move_rows(lga: Lc0GameAnalysis | None) -> list[MoveRow] | None:
    """Convert Lc0 analysis moves to MoveRow objects, or None if no analysis."""
    if lga is None:
        return None
    return [
        MoveRow(
            ply=m.ply,
            san=m.san,
            fen=m.fen,
            wdl_win=m.wdl_win,
            wdl_draw=m.wdl_draw,
            wdl_loss=m.wdl_loss,
            cp_equiv=m.cp_equiv,
            best_move=m.best_move or "",
            arrow_uci=m.arrow_uci or "",
            arrow_uci_2=m.arrow_uci_2 or "",
            arrow_uci_3=m.arrow_uci_3 or "",
            arrow_score_1=m.arrow_score_1,
            arrow_score_2=m.arrow_score_2,
            arrow_score_3=m.arrow_score_3,
            move_win_delta=m.move_win_delta,
            classification=m.classification,
            pv_san_1=m.pv_san_1,
            pv_san_2=m.pv_san_2,
            pv_san_3=m.pv_san_3,
        )
        for m in lga.moves.order_by("ply")
    ]


def _lc0_summary_kwargs(lga: Lc0GameAnalysis | None) -> dict:
    """Build a dict of Lc0 summary stats for GameAnalysisData initialization."""
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
