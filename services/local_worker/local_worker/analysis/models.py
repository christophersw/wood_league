"""
Title: models.py — Analysis result dataclasses
Description:
    Dataclasses representing per-move and per-game analysis results for both
    Stockfish and Lc0 engines.

Changelog:
    2026-05-09: Initial creation
    2026-05-19: Lc0MoveResult gains rescaled WDL fields (wdl_*_adj, wdl_mu,
                delta_mu, delta_d), renames classification to base_severity,
                and adds draw_character (issue #159 Phase C1).
                Lc0GameResult gains draw_rate_reference, wdl_calibration_elo,
                contempt (issue #159 Phase C1).
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
    """Per-move result from Lc0 analysis (raw + Elo-rescaled)."""

    ply: int
    san: str
    fen: str
    wdl_win: int          # RAW network permille, White frame (cache-shareable)
    wdl_draw: int
    wdl_loss: int
    wdl_win_adj: int      # rescaled permille, White frame
    wdl_draw_adj: int
    wdl_loss_adj: int
    # Expected-score fraction in [0,1] computed as (W + 0.5·D) / total from the
    # RESCALED White-frame triple. NOT lc0's internal logit-space mu — those
    # are different quantities. Do not substitute RescaledWDL.mu here.
    wdl_mu: Optional[float]
    delta_mu: Optional[float]
    delta_d: Optional[float]
    cp_equiv: Optional[int]   # objective, from RAW Q (unchanged)
    best_move: str
    arrow_uci: str
    arrow_uci_2: str
    arrow_uci_3: str
    arrow_score_1: Optional[float]
    arrow_score_2: Optional[float]
    arrow_score_3: Optional[float]
    move_win_delta: float
    base_severity: str
    draw_character: Optional[str]
    pv_san_1: Optional[str]
    pv_san_2: Optional[str]
    pv_san_3: Optional[str]


@dataclass
class Lc0GameResult:
    """Aggregated Lc0 analysis result for a full game."""

    engine_nodes: int
    network_name: str
    draw_rate_reference: float
    wdl_calibration_elo: int
    contempt: int
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
