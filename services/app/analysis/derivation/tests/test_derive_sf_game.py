"""
Title: test_derive_sf_game.py — Stockfish game-derivation orchestrator
Description:
    Issue #161 Phase E. Structural tests for ``derive_sf_game``: it consumes
    a raw Stockfish payload (per the #161 contract) plus a ``Game`` stub and
    returns a dict ready for ``GameAnalysis`` / ``MoveAnalysis`` creation.
    Pins the output shape, per-move derivations, side-aware aggregates, and
    chained-eval semantics. Band-ladder correctness is covered by
    ``test_sf_golden.py``.

Changelog:
    2026-05-19 (#161/E): Initial.
"""
from __future__ import annotations

import pytest

from analysis.derivation.stockfish import derive_sf_game


def _raw_move(
    ply: int, *, cp_eval: int = 0, mate_in: int | None = None,
    arrow_cp_1: float | None = None, arrow_cp_2: float | None = None,
    san: str = "—", fen: str = "—", arrow_uci_1: str = "e2e4",
) -> dict:
    """Build a minimal SF move entry matching the raw contract."""
    return {
        "ply": ply, "san": san, "fen": fen,
        "cp_eval": cp_eval, "mate_in": mate_in,
        "arrow_uci_1": arrow_uci_1,
        "arrow_cp_1": arrow_cp_1,
        "arrow_cp_2": arrow_cp_2,
    }


def _payload(moves: list[dict], depth: int = 20) -> dict:
    """Wrap moves in the canonical raw SF payload envelope."""
    return {
        "worker_id": "w", "engine_depth": depth,
        "engine_name": "Stockfish 16", "moves": moves,
    }


def test_top_level_shape() -> None:
    """The orchestrator returns every game-level field GameAnalysis expects."""
    out = derive_sf_game(_payload([_raw_move(1, cp_eval=30)]), None)
    expected = {
        "engine_depth", "summary_cp",
        # #188 Phase B: NPV surfaced at the top level (nullable for older SF builds).
        "normalize_to_pawn_value",
        "white_accuracy", "black_accuracy",
        "white_acpl", "black_acpl",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
        "moves",
    }
    assert set(out) == expected
    assert out["engine_depth"] == 20


def test_summary_cp_is_terminal_position_eval() -> None:
    """summary_cp echoes the last move's white-frame cp."""
    moves = [_raw_move(1, cp_eval=50), _raw_move(2, cp_eval=-40), _raw_move(3, cp_eval=120)]
    out = derive_sf_game(_payload(moves), None)
    assert out["summary_cp"] == 120


def test_first_move_cpl_chained_from_zero() -> None:
    """Ply 1's CPL is computed against the starting position (0 cp)."""
    # White drops from 0 to -200 → mover-frame CPL = 200.
    out = derive_sf_game(_payload([_raw_move(1, cp_eval=-200)]), None)
    assert out["moves"][0]["cpl"] == 200


def test_chained_cpl_uses_prev_move_eval() -> None:
    """Ply N's CPL uses ply N-1's cp_eval as the 'before' eval."""
    # ply 1 (white): 0 → -50  → white cpl 50
    # ply 2 (black): -50 → -10 → black cpl 40 (Black's eval went from +50 to +10)
    out = derive_sf_game(
        _payload([_raw_move(1, cp_eval=-50), _raw_move(2, cp_eval=-10)]), None,
    )
    assert out["moves"][0]["cpl"] == 50
    assert out["moves"][1]["cpl"] == 40


def test_mate_in_flattens_cp_to_mate_score() -> None:
    """A non-null mate_in overrides cp_eval with ±MATE_SCORE for sigmoid saturation."""
    out = derive_sf_game(_payload([_raw_move(1, cp_eval=42, mate_in=3)]), None)
    move = out["moves"][0]
    # White wins by mate → mover_cp_after = +MATE_SCORE → CPL = 0 (gain not credited).
    assert move["cpl"] == 0


def test_classification_uses_band_ladder() -> None:
    """A CPL of 200 (Mistake band) lands in the right severity bucket."""
    # Ply 1: 0 → -200 → mover CPL 200 → Mistake.
    out = derive_sf_game(_payload([_raw_move(1, cp_eval=-200)]), None)
    assert out["moves"][0]["classification"] == "Mistake"


def test_classification_top_tier_with_candidate_cp_gap() -> None:
    """A CPL<10 move with a big native candidate-cp gap classifies as Great."""
    # White mover; candidate cps 200 vs 50 → mover-frame gap 150 > SF_GREAT_GAP (80).
    out = derive_sf_game(_payload([
        _raw_move(1, cp_eval=10, arrow_cp_1=200.0, arrow_cp_2=50.0),
    ]), None)
    assert out["moves"][0]["classification"] in {"Great", "Brilliant"}


def test_classification_black_mover_candidate_cp_gap() -> None:
    """Black-mover gap uses mover frame: more-negative White cp is the better line.

    Regression for the #156-class frame hazard. Black mover, candidate White-frame
    cps -200 (best for Black) vs -50 → mover-frame gap = 200 - 50 = 150 > Great.
    """
    out = derive_sf_game(_payload([
        _raw_move(1, cp_eval=0),
        _raw_move(2, cp_eval=-10, arrow_cp_1=-200.0, arrow_cp_2=-50.0),
    ]), None)
    assert out["moves"][1]["classification"] in {"Great", "Brilliant"}


def test_counters_reflect_mover_side_severities() -> None:
    """Per-side counters bin classifications by ply parity."""
    moves = [
        _raw_move(1, cp_eval=-400),  # White blunder (0→-400)
        _raw_move(2, cp_eval=-380),  # Black inaccuracy-ish (Black's eval 400→380)
        _raw_move(3, cp_eval=-700),  # White blunder again
    ]
    out = derive_sf_game(_payload(moves), None)
    total_white_counters = (
        out["white_blunders"] + out["white_mistakes"] + out["white_inaccuracies"]
    )
    total_black_counters = (
        out["black_blunders"] + out["black_mistakes"] + out["black_inaccuracies"]
    )
    assert total_white_counters >= 1
    assert total_white_counters + total_black_counters <= 3


def test_per_move_payload_carries_raw_and_derived_fields() -> None:
    """Every move dict surfaces the canonical raw + derived field set."""
    out = derive_sf_game(_payload([_raw_move(1, cp_eval=30)]), None)
    move = out["moves"][0]
    for field in (
        "ply", "san", "fen",
        "cp_eval", "mate_in",
        "arrow_uci_1", "arrow_uci_2", "arrow_uci_3",
        "arrow_cp_1", "arrow_cp_2", "arrow_cp_3",
        "pv_san_1", "pv_san_2", "pv_san_3",
        "wdl_win", "wdl_draw", "wdl_loss",
        "wdl_win_1", "wdl_draw_1", "wdl_loss_1",
        "wdl_win_2", "wdl_draw_2", "wdl_loss_2",
        "wdl_win_3", "wdl_draw_3", "wdl_loss_3",
        "wdl_win_adj", "wdl_draw_adj", "wdl_loss_adj",
        "cpl", "move_win_delta", "classification", "best_move",
    ):
        assert field in move, field
    assert "_move_acc" not in move
    assert "_cp_after_white" not in move


def test_accuracy_in_unit_range_scaled_by_100() -> None:
    """Per-side accuracy always lies in [0, 100]."""
    moves = [_raw_move(p, cp_eval=20 * (-1) ** p) for p in range(1, 9)]
    out = derive_sf_game(_payload(moves), None)
    assert 0.0 <= out["white_accuracy"] <= 100.0
    assert 0.0 <= out["black_accuracy"] <= 100.0


def test_acpl_is_zero_when_no_loss_on_side() -> None:
    """A side that played only optimal-evaluation moves has zero ACPL."""
    # All zeros → no drops → CPL = 0 on every ply → ACPL = 0.
    moves = [_raw_move(p, cp_eval=0) for p in range(1, 5)]
    out = derive_sf_game(_payload(moves), None)
    assert out["white_acpl"] == pytest.approx(0.0)
    assert out["black_acpl"] == pytest.approx(0.0)


def test_orchestrator_preserves_move_order() -> None:
    """Returned ``moves`` list is in input-ply order."""
    moves = [_raw_move(p, cp_eval=0) for p in (1, 2, 3, 4, 5)]
    out = derive_sf_game(_payload(moves), None)
    assert [m["ply"] for m in out["moves"]] == [1, 2, 3, 4, 5]
