"""
Title: services_v2.py — New-schema-only game analysis loader
Description:
    Loads game analysis using ONLY the raw+derived columns introduced in
    #161 / #163 / #165 / #184. Returns None for games whose analyses
    predate the new derived fields so callers can show a re-analyze banner.

Changelog:
    2026-05-21 (#186): Initial — rewrite of services.py for the analysis page.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import chess.pgn

from analysis.models import GameAnalysis, Lc0GameAnalysis
from games.models import Game
from openings.models import OpeningBook


@dataclass
class SfMoveRow:
    """Per-ply Stockfish data read from the new schema."""

    ply: int
    san: str
    fen: str
    cp_eval: float
    mate_in: int | None
    cpl: float | None
    move_win_delta: float | None
    classification: str | None
    best_move: str
    arrow_uci_1: str
    arrow_uci_2: str | None
    arrow_uci_3: str | None
    arrow_score_1: float | None
    arrow_score_2: float | None
    arrow_score_3: float | None
    pv_san_1: str | None
    pv_san_2: str | None
    pv_san_3: str | None


@dataclass
class Lc0MoveRow:
    """Per-ply LC0 data — White-frame WDL + both classification levels."""

    ply: int
    san: str
    fen: str
    wdl_win_adj: int | None
    wdl_draw_adj: int | None
    wdl_loss_adj: int | None
    wdl_mu: float | None
    delta_mu: float | None
    delta_d: float | None
    base_severity: str | None
    draw_character: str | None
    best_move: str
    arrow_uci_1: str
    arrow_uci_2: str | None
    arrow_uci_3: str | None
    pv_san_1: str | None
    pv_san_2: str | None
    pv_san_3: str | None


@dataclass
class GameAnalysisDataV2:
    """Headline + per-side + per-ply game analysis, new schema only."""

    game_id: str
    slug: str
    white: str
    black: str
    white_rating: int | None
    black_rating: int | None
    result: str
    pgn: str
    date: str
    time_control: str
    url: str
    eco_code: str
    opening_name: str
    lichess_opening: str | None
    opening_id: int | None
    # Stockfish
    sf_moves: list[SfMoveRow] = field(default_factory=list)
    sf_white_accuracy: float | None = None
    sf_black_accuracy: float | None = None
    sf_white_acpl: float | None = None
    sf_black_acpl: float | None = None
    sf_white_blunders: int | None = None
    sf_white_mistakes: int | None = None
    sf_white_inaccuracies: int | None = None
    sf_black_blunders: int | None = None
    sf_black_mistakes: int | None = None
    sf_black_inaccuracies: int | None = None
    sf_engine_depth: int | None = None
    sf_analyzed_at: str = ""
    # LC0
    lc0_moves: list[Lc0MoveRow] = field(default_factory=list)
    lc0_white_accuracy: float | None = None
    lc0_black_accuracy: float | None = None
    lc0_white_win_prob: float | None = None
    lc0_white_draw_prob: float | None = None
    lc0_white_loss_prob: float | None = None
    lc0_network_name: str | None = None
    lc0_engine_nodes: int | None = None
    lc0_contempt: int | None = None
    lc0_draw_rate_reference: float | None = None
    lc0_calibration_elo: int | None = None
    lc0_analyzed_at: str = ""

    @property
    def has_sf(self) -> bool:
        """Return True when at least one new-schema SF move row is present."""
        return bool(self.sf_moves)

    @property
    def has_lc0(self) -> bool:
        """Return True when at least one new-schema LC0 move row is present."""
        return bool(self.lc0_moves)

    @property
    def white_label(self) -> str:
        """Return the White player display label with optional rating.

        Returns:
            str: '<name> (<rating>)' when rating is set, else '<name>'.
        """
        return f"{self.white} ({self.white_rating})" if self.white_rating else self.white

    @property
    def black_label(self) -> str:
        """Return the Black player display label with optional rating.

        Returns:
            str: '<name> (<rating>)' when rating is set, else '<name>'.
        """
        return f"{self.black} ({self.black_rating})" if self.black_rating else self.black


def _sf_rows(ga: GameAnalysis | None) -> list[SfMoveRow]:
    """Build a list of SfMoveRow from a GameAnalysis, applying the new-schema gate.

    Parameters:
        ga (GameAnalysis | None): The game-level SF analysis record, or None.

    Returns:
        list[SfMoveRow]: Non-empty list if every row has a non-null
            move_win_delta; empty list otherwise (legacy or missing data).
    """
    if ga is None or ga.analyzed_at is None:
        return []
    rows = list(ga.moves.order_by("ply"))
    # New-schema gate: every row must have a non-null move_win_delta.
    if not rows or any(r.move_win_delta is None for r in rows):
        return []
    return [
        SfMoveRow(
            ply=r.ply, san=r.san, fen=r.fen,
            cp_eval=r.cp_eval, mate_in=r.mate_in,
            cpl=r.cpl, move_win_delta=r.move_win_delta,
            classification=r.classification, best_move=r.best_move or "",
            arrow_uci_1=r.arrow_uci_1 or "",
            arrow_uci_2=r.arrow_uci_2, arrow_uci_3=r.arrow_uci_3,
            arrow_score_1=r.arrow_score_1, arrow_score_2=r.arrow_score_2,
            arrow_score_3=r.arrow_score_3,
            pv_san_1=r.pv_san_1, pv_san_2=r.pv_san_2, pv_san_3=r.pv_san_3,
        )
        for r in rows
    ]


def _lc0_rows(lga: Lc0GameAnalysis | None) -> list[Lc0MoveRow]:
    """Build a list of Lc0MoveRow from a Lc0GameAnalysis, applying the new-schema gate.

    Parameters:
        lga (Lc0GameAnalysis | None): The game-level LC0 analysis record, or None.

    Returns:
        list[Lc0MoveRow]: Non-empty list if every row has a non-null
            wdl_win_adj; empty list otherwise (legacy or missing data).
    """
    if lga is None or lga.analyzed_at is None:
        return []
    rows = list(lga.moves.order_by("ply"))
    # New-schema gate: every row must have White-frame adj columns populated.
    if not rows or any(r.wdl_win_adj is None for r in rows):
        return []
    return [
        Lc0MoveRow(
            ply=r.ply, san=r.san, fen=r.fen,
            wdl_win_adj=r.wdl_win_adj, wdl_draw_adj=r.wdl_draw_adj,
            wdl_loss_adj=r.wdl_loss_adj,
            wdl_mu=r.wdl_mu, delta_mu=r.delta_mu, delta_d=r.delta_d,
            base_severity=r.base_severity, draw_character=r.draw_character,
            best_move=r.best_move or "",
            arrow_uci_1=r.arrow_uci_1 or "",
            arrow_uci_2=r.arrow_uci_2, arrow_uci_3=r.arrow_uci_3,
            pv_san_1=r.pv_san_1, pv_san_2=r.pv_san_2, pv_san_3=r.pv_san_3,
        )
        for r in rows
    ]


def get_game_analysis_v2(slug: str) -> GameAnalysisDataV2 | None:
    """Return new-schema analysis for the given slug, or None.

    Parameters:
        slug (str): The Game.slug to look up.

    Returns:
        GameAnalysisDataV2 | None: Populated dataclass when at least one
            engine (SF or LC0) has fully derived new-schema rows; None when
            the game is missing, has no parseable PGN, or both engines have
            only legacy (pre-derived) rows. Callers should render the
            re-analyze banner when this returns None.
    """
    try:
        db_game = Game.objects.get(slug=slug)
    except Game.DoesNotExist:
        return None

    pgn_text = db_game.pgn or ""
    pgn_game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None
    if pgn_game is None:
        return None

    try:
        ga = db_game.analysis
    except GameAnalysis.DoesNotExist:
        ga = None
    try:
        lga = db_game.lc0_analysis
    except Lc0GameAnalysis.DoesNotExist:
        lga = None

    sf_moves = _sf_rows(ga)
    lc0_moves = _lc0_rows(lga)
    if not sf_moves and not lc0_moves:
        return None

    opening_id = None
    if db_game.eco_code:
        opening_id = (
            OpeningBook.objects.filter(eco=db_game.eco_code)
            .values_list("id", flat=True)
            .first()
        )

    date = (
        db_game.played_at.strftime("%Y-%m-%d %H:%M")
        if db_game.played_at
        else pgn_game.headers.get("Date", "")
    )

    data = GameAnalysisDataV2(
        game_id=db_game.id,
        slug=db_game.slug,
        white=db_game.white_username or pgn_game.headers.get("White", "White"),
        black=db_game.black_username or pgn_game.headers.get("Black", "Black"),
        white_rating=db_game.white_rating,
        black_rating=db_game.black_rating,
        result=db_game.result_pgn or pgn_game.headers.get("Result", "*"),
        pgn=pgn_text,
        date=date,
        time_control=db_game.time_control or pgn_game.headers.get("TimeControl", ""),
        url=pgn_game.headers.get("Link", ""),
        eco_code=db_game.eco_code or "",
        opening_name=db_game.opening_name or "",
        lichess_opening=db_game.lichess_opening,
        opening_id=opening_id,
        sf_moves=sf_moves,
        lc0_moves=lc0_moves,
    )

    if ga is not None and sf_moves:
        data.sf_white_accuracy = ga.white_accuracy
        data.sf_black_accuracy = ga.black_accuracy
        data.sf_white_acpl = ga.white_acpl
        data.sf_black_acpl = ga.black_acpl
        data.sf_white_blunders = ga.white_blunders
        data.sf_white_mistakes = ga.white_mistakes
        data.sf_white_inaccuracies = ga.white_inaccuracies
        data.sf_black_blunders = ga.black_blunders
        data.sf_black_mistakes = ga.black_mistakes
        data.sf_black_inaccuracies = ga.black_inaccuracies
        data.sf_engine_depth = ga.engine_depth
        data.sf_analyzed_at = ga.analyzed_at.isoformat() if ga.analyzed_at else ""

    if lga is not None and lc0_moves:
        data.lc0_white_accuracy = lga.white_accuracy
        data.lc0_black_accuracy = lga.black_accuracy
        data.lc0_white_win_prob = lga.white_win_prob
        data.lc0_white_draw_prob = lga.white_draw_prob
        data.lc0_white_loss_prob = lga.white_loss_prob
        data.lc0_network_name = lga.network_name
        data.lc0_engine_nodes = lga.engine_nodes
        data.lc0_contempt = lga.contempt
        data.lc0_draw_rate_reference = lga.draw_rate_reference
        data.lc0_calibration_elo = lga.wdl_calibration_elo
        data.lc0_analyzed_at = lga.analyzed_at.isoformat() if lga.analyzed_at else ""

    return data
