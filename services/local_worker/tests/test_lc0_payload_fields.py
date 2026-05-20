"""
Title: test_lc0_payload_fields.py — Payload provenance and per-move WDL fields
Description:
    Verifies that build_lc0_payload() carries draw_rate_reference, wdl_calibration_elo,
    contempt at the top level, and per-move wdl_win_adj/wdl_draw_adj/wdl_loss_adj/
    wdl_mu/delta_mu/delta_d/base_severity/draw_character in each move dict.
    Also confirms the old 'classification' key is removed.

Changelog:
    2026-05-19: Initial creation (issue #159 Phase C3)
"""
from __future__ import annotations

from local_worker.analysis.models import Lc0MoveResult, Lc0GameResult
from local_worker.analysis.lc0 import build_lc0_payload


def _g() -> Lc0GameResult:
    """Build a minimal Lc0GameResult with one move for payload tests."""
    move = Lc0MoveResult(
        ply=1,
        san="e4",
        fen="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        wdl_win=510,
        wdl_draw=310,
        wdl_loss=180,
        wdl_win_adj=490,
        wdl_draw_adj=320,
        wdl_loss_adj=190,
        wdl_mu=0.665,
        delta_mu=0.01,
        delta_d=0.005,
        cp_equiv=22,
        best_move="e4",
        arrow_uci="e2e4",
        arrow_uci_2="",
        arrow_uci_3="",
        arrow_score_1=None,
        arrow_score_2=None,
        arrow_score_3=None,
        move_win_delta=0.5,
        base_severity="Best",
        draw_character=None,
        pv_san_1=None,
        pv_san_2=None,
        pv_san_3=None,
    )
    return Lc0GameResult(
        engine_nodes=10000,
        network_name="BT4",
        draw_rate_reference=0.45,
        wdl_calibration_elo=1500,
        contempt=0,
        white_win_prob=0.51,
        white_draw_prob=0.31,
        white_loss_prob=0.18,
        black_win_prob=0.18,
        black_draw_prob=0.31,
        black_loss_prob=0.51,
        white_blunders=0,
        white_mistakes=0,
        white_inaccuracies=0,
        black_blunders=0,
        black_mistakes=0,
        black_inaccuracies=0,
        moves=[move],
    )


def test_payload_carries_provenance_and_move_fields():
    """build_lc0_payload must expose calibration provenance and rescaled WDL per move."""
    payload = build_lc0_payload(_g(), worker_id="test-worker")

    # Top-level calibration provenance
    assert payload["draw_rate_reference"] == 0.45
    assert payload["wdl_calibration_elo"] == 1500
    assert payload["contempt"] == 0

    # Per-move rescaled WDL fields
    assert len(payload["moves"]) == 1
    m = payload["moves"][0]
    assert m["wdl_win_adj"] == 490
    assert m["wdl_draw_adj"] == 320
    assert m["wdl_loss_adj"] == 190
    assert m["wdl_mu"] == 0.665
    assert m["delta_mu"] == 0.01
    assert m["delta_d"] == 0.005
    assert m["base_severity"] == "Best"
    assert m["draw_character"] is None

    # Old 'classification' key must be gone
    assert "classification" not in m
