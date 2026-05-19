"""
Title: test_wdl_calibration_rescale.py — Tests for rescale_wdl facade
Description:
    Verifies the verbatim lc0 WDLRescale port and the rescale_wdl public
    facade: eps-guard passthrough, white-frame orientation, and sign-flip
    on side-to-move.
Changelog:
    2026-05-19: Initial creation (issue #159, Task A3).
"""
from local_worker.analysis.wdl_calibration import rescale_wdl


def test_extreme_wdl_passthrough():
    out = rescale_wdl(0, 0, 1000, white_elo=1100, black_elo=1100,
                      white_to_move=True, draw_rate_reference=0.58)
    assert out.wdl_white == (0, 0, 1000)
    assert out.mu == 0.0


def test_symmetric_calibration_keeps_white_frame_orientation():
    out = rescale_wdl(500, 300, 200, white_elo=1100, black_elo=1100,
                      white_to_move=True, draw_rate_reference=0.58)
    win, draw, loss = out.wdl_white
    assert win + draw + loss == 1000
    assert win > loss


def test_black_to_move_sign_flips():
    a = rescale_wdl(500, 300, 200, white_elo=900, black_elo=1300,
                    white_to_move=True, draw_rate_reference=0.58)
    b = rescale_wdl(500, 300, 200, white_elo=900, black_elo=1300,
                    white_to_move=False, draw_rate_reference=0.58)
    assert a.wdl_white != b.wdl_white
