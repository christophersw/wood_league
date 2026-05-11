"""
Title: models.py — Analysis result dataclasses
Description:
    Dataclasses representing per-move and per-game analysis results for both
    Stockfish and Lc0 engines.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StockfishMoveResult:
    """Per-move result from Stockfish analysis.

    The arrow_* and pv_san_* fields carry MultiPV candidate information for the
    top up-to-three engine lines before the played move. Empty arrows are ""
    and missing scores / PV strings are None — mirroring Lc0MoveResult so that
    StockfishCompleteSerializer can accept the same shape via .get() defaults.
    """

    ply: int
    san: str
    fen: str
    cp_eval: int
    cpl: int
    best_move: str
    classification: str
    arrow_uci: str = ""
    arrow_uci_2: str = ""
    arrow_uci_3: str = ""
    arrow_score_1: Optional[float] = None
    arrow_score_2: Optional[float] = None
    arrow_score_3: Optional[float] = None
    pv_san_1: Optional[str] = None
    pv_san_2: Optional[str] = None
    pv_san_3: Optional[str] = None


@dataclass
class StockfishGameResult:
    """Aggregated Stockfish analysis result for a full game."""

    engine_depth: int
    white_accuracy: float
    black_accuracy: float
    white_acpl: float
    black_acpl: float
    white_blunders: int
    white_mistakes: int
    white_inaccuracies: int
    black_blunders: int
    black_mistakes: int
    black_inaccuracies: int
    moves: list[StockfishMoveResult] = field(default_factory=list)


@dataclass
class Lc0MoveResult:
    """Per-move result from Lc0 analysis."""

    ply: int
    san: str
    fen: str
    wdl_win: int
    wdl_draw: int
    wdl_loss: int
    cp_equiv: Optional[int]
    best_move: str
    arrow_uci: str
    arrow_uci_2: str
    arrow_uci_3: str
    arrow_score_1: Optional[float]
    arrow_score_2: Optional[float]
    arrow_score_3: Optional[float]
    move_win_delta: float
    classification: str
    pv_san_1: Optional[str]
    pv_san_2: Optional[str]
    pv_san_3: Optional[str]


@dataclass
class Lc0GameResult:
    """Aggregated Lc0 analysis result for a full game."""

    engine_nodes: int
    network_name: str
    white_win_prob: float
    white_draw_prob: float
    white_loss_prob: float
    black_win_prob: float
    black_draw_prob: float
    black_loss_prob: float
    white_blunders: int
    white_mistakes: int
    white_inaccuracies: int
    black_blunders: int
    black_mistakes: int
    black_inaccuracies: int
    moves: list[Lc0MoveResult] = field(default_factory=list)
