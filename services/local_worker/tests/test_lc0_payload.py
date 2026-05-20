"""
Title: test_lc0_payload.py — Tests for Lc0 payload building
Description:
    Tests that build_lc0_payload() produces a valid API payload from pre-canned results.

Changelog:
    2026-05-09: Initial creation
    2026-05-19: Updated for C1 field renames (classification->base_severity, new
                rescaled WDL fields, Lc0GameResult provenance fields) (issue #159).
"""
import pytest
from local_worker.analysis.models import Lc0MoveResult, Lc0GameResult
from local_worker.analysis.lc0 import build_lc0_payload


def test_payload_structure():
    game = Lc0GameResult(
        engine_nodes=10000,
        network_name="BT4",
        draw_rate_reference=0.45,
        wdl_calibration_elo=1500,
        contempt=0,
        white_win_prob=0.42,
        white_draw_prob=0.35,
        white_loss_prob=0.23,
        black_win_prob=0.23,
        black_draw_prob=0.35,
        black_loss_prob=0.42,
        white_blunders=0,
        white_mistakes=1,
        white_inaccuracies=2,
        black_blunders=1,
        black_mistakes=0,
        black_inaccuracies=1,
        moves=[
            Lc0MoveResult(
                ply=1, san="d4",
                fen="rnbqkbnr/pppppppp/8/8/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 1",
                wdl_win=420, wdl_draw=350, wdl_loss=230,
                wdl_win_adj=410, wdl_draw_adj=355, wdl_loss_adj=235,
                wdl_mu=0.59, delta_mu=0.005, delta_d=0.002,
                cp_equiv=28, best_move="d4",
                arrow_uci="d2d4", arrow_uci_2="", arrow_uci_3="",
                arrow_score_1=None, arrow_score_2=None, arrow_score_3=None,
                move_win_delta=0.7, base_severity="Best", draw_character=None,
                pv_san_1=None, pv_san_2=None, pv_san_3=None,
            )
        ],
    )
    payload = build_lc0_payload(game, worker_id="test-lc0")
    assert payload["engine"] == "lc0"
    assert payload["worker_id"] == "test-lc0"
    assert payload["engine_nodes"] == 10000
    assert payload["network_name"] == "BT4"
    assert len(payload["moves"]) == 1
    m = payload["moves"][0]
    assert m["wdl_win"] == 420
    assert m["base_severity"] == "Best"
    assert "classification" not in m
    assert m["move_win_delta"] == pytest.approx(0.7)
