"""
Title: test_wdl_calibration_params.py — tests for lc0 Elo->WDLRescale param ports
Description:
    Verifies convert_regular_to_game_pair_elo and simplified_wdl_rescale_params
    against expected mathematical properties (monotonicity, symmetry, sign).
Changelog:
    2026-05-19: Initial creation (issue #159, task A2).
"""
from local_worker.analysis.wdl_calibration import (
    convert_regular_to_game_pair_elo,
    simplified_wdl_rescale_params,
)


def test_game_pair_elo_increases_monotonically():
    a = convert_regular_to_game_pair_elo(1000.0)
    b = convert_regular_to_game_pair_elo(1500.0)
    assert b > a > 1000.0


def test_symmetric_pair_has_zero_diff():
    ratio, diff = simplified_wdl_rescale_params(
        contempt=0.0, draw_rate_reference=0.58, elo_active=1100.0,
        contempt_max=420.0, contempt_attenuation=1.0)
    assert abs(diff) < 1e-6
    assert ratio > 0.0


def test_asymmetric_pair_diff_sign():
    _, diff_pos = simplified_wdl_rescale_params(300.0, 0.58, 1200.0, 420.0, 1.0)
    _, diff_neg = simplified_wdl_rescale_params(-300.0, 0.58, 900.0, 420.0, 1.0)
    assert diff_pos > 0.0 > diff_neg


def test_asymmetric_values_are_pinned():
    # regression guard; ground truth vs lc0 itself is verified in Task A5
    r1, d1 = simplified_wdl_rescale_params(-400.0, 0.58, 900.0, 420.0, 1.0)
    assert abs(r1 - 7.740090370178223) <= 1e-6 and abs(d1 - (-23.3478946685791)) <= 1e-6
    r2, d2 = simplified_wdl_rescale_params(300.0, 0.58, 1200.0, 420.0, 1.0)
    assert abs(r2 - 7.969476699829102) <= 1e-6 and abs(d2 - 18.132747650146484) <= 1e-6
