"""
Title: models.py — Analysis result dataclasses (raw-only after #161 Phase H)
Description:
    Dataclasses representing per-move and per-game analysis results for both
    Stockfish and Lc0 engines. After issue #161 Phase H, every derived /
    classified / calibrated / aggregated field has been moved app-side; the
    worker emits raw engine observables only.

Changelog:
    2026-05-09: Initial creation.
    2026-05-19 (#159): Lc0MoveResult gained rescaled WDL + severity fields;
        Lc0GameResult gained draw_rate_reference / wdl_calibration_elo /
        contempt for the #159 calibration architecture.
    2026-05-20 (#161/H): Strip every derived field. Workers now produce only
        the raw payload contract; ``analysis.derivation`` (app-side) computes
        accuracy, CPL, classifications, counters, rescale, severity.
    2026-05-21 (#188/A): Stockfish dataclasses gained mover-frame WDL triples
        (played move + 3 candidates) plus game-level NormalizeToPawnValue.
        All nullable for older SF builds without UCI_ShowWDL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StockfishMoveResult:
    """Raw per-move Stockfish observables (#161 Phase H).

    cp_eval is white-frame post-move cp; mate_in is the signed mate distance
    (positive = White mates) or None when no mate score. arrow_uci_* carry the
    top-3 MultiPV candidates' UCIs and arrow_cp_* their White-frame centipawn
    evals, from the position *before* the played move.
    """

    ply: int
    san: str
    fen: str
    cp_eval: int
    mate_in: Optional[int] = None
    arrow_uci_1: str = ""
    arrow_uci_2: Optional[str] = None
    arrow_uci_3: Optional[str] = None
    pv_san_1: Optional[str] = None
    pv_san_2: Optional[str] = None
    pv_san_3: Optional[str] = None
    # Raw SF WDL triple, mover frame, milli-units (#188 Phase A).
    # Nullable: older SF builds without UCI_ShowWDL or unreachable triples → None.
    wdl_win: Optional[int] = None
    wdl_draw: Optional[int] = None
    wdl_loss: Optional[int] = None
    # Per-candidate raw WDL triples (top 3 MultiPV); fully nullable per line.
    wdl_win_1: Optional[int] = None
    wdl_draw_1: Optional[int] = None
    wdl_loss_1: Optional[int] = None
    wdl_win_2: Optional[int] = None
    wdl_draw_2: Optional[int] = None
    wdl_loss_2: Optional[int] = None
    wdl_win_3: Optional[int] = None
    wdl_draw_3: Optional[int] = None
    wdl_loss_3: Optional[int] = None
    # Per-candidate White-frame centipawn evals (#188 Phase D). Native source
    # for the app's classifier second-best gap; nullable per line.
    arrow_cp_1: Optional[int] = None
    arrow_cp_2: Optional[int] = None
    arrow_cp_3: Optional[int] = None


@dataclass
class StockfishGameResult:
    """Raw game-level Stockfish observables (#161 Phase H)."""

    engine_depth: int
    engine_name: str = ""
    moves: list[StockfishMoveResult] = field(default_factory=list)
    # Engine build constant captured at analyse time (#188 Phase A).
    # Nullable for older SF builds that don't expose it as a UCI option.
    normalize_to_pawn_value: Optional[int] = None


@dataclass
class Lc0MoveResult:
    """Raw per-move Lc0 observables (#161 Phase H).

    All WDL triples are in *mover frame* + milli-units (0-1000). Per-candidate
    triples (wdl_*_1/2/3) come from the position-before-move MultiPV
    evaluation; they're nullable per-line because MultiPV may produce fewer
    than 3 lines (and Phase H optionally leaves them None until the lc0
    analyzer wires MultiPV WDL extraction — the serializer accepts None).
    """

    ply: int
    san: str
    fen: str
    # Played-move triple (mover frame).
    wdl_win: int
    wdl_draw: int
    wdl_loss: int
    # Top-3 candidate UCIs.
    arrow_uci_1: str = ""
    arrow_uci_2: Optional[str] = None
    arrow_uci_3: Optional[str] = None
    # Per-candidate raw WDL triples.
    wdl_win_1: Optional[int] = None
    wdl_draw_1: Optional[int] = None
    wdl_loss_1: Optional[int] = None
    wdl_win_2: Optional[int] = None
    wdl_draw_2: Optional[int] = None
    wdl_loss_2: Optional[int] = None
    wdl_win_3: Optional[int] = None
    wdl_draw_3: Optional[int] = None
    wdl_loss_3: Optional[int] = None
    pv_san_1: Optional[str] = None
    pv_san_2: Optional[str] = None
    pv_san_3: Optional[str] = None


@dataclass
class Lc0GameResult:
    """Raw game-level Lc0 observables (#161 Phase H).

    ``draw_rate_reference`` is echoed from the calibration-row value the app
    attached to the job at checkout time (Phase B). The worker treats it as
    opaque payload metadata — derivation runs app-side.
    """

    engine_nodes: int
    network_name: str
    draw_rate_reference: float
    moves: list[Lc0MoveResult] = field(default_factory=list)
