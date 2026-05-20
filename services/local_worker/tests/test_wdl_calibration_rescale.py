"""
Title: test_wdl_calibration_rescale.py — Tests for rescale_wdl facade
Description:
    Verifies the verbatim lc0 WDLRescale port and the rescale_wdl public
    facade: eps-guard passthrough, white-frame orientation, frame invariance
    under side-to-move, and calibration direction relative to player strengths.
Changelog:
    2026-05-19: Initial creation (issue #159, Task A3).
    2026-05-19: Replace incorrect sign-flip test with frame-invariance and
                calibration-direction tests (issue #159, Task A3 Fix 2).
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


def test_frame_invariance_requires_correct_sign():
    # Same White-frame raw WDL must yield the same White-frame rescaled
    # output regardless of side-to-move — this holds ONLY when the
    # side-dependent sign (+1 white / -1 black) is correct. A constant
    # sign breaks this invariance.
    kw = dict(white_elo=900, black_elo=1300, draw_rate_reference=0.58)
    a = rescale_wdl(500, 300, 200, white_to_move=True, **kw)
    b = rescale_wdl(500, 300, 200, white_to_move=False, **kw)
    assert a.wdl_white == b.wdl_white


def test_calibration_shifts_toward_stronger_player():
    # White much weaker (900 vs 1300): practical White win% must drop
    # below the raw 500 permille. White much stronger: must rise above.
    weak = rescale_wdl(500, 300, 200, white_elo=900, black_elo=1300,
                        white_to_move=True, draw_rate_reference=0.58)
    strong = rescale_wdl(500, 300, 200, white_elo=1300, black_elo=900,
                         white_to_move=True, draw_rate_reference=0.58)
    assert weak.wdl_white[0] < 500 < strong.wdl_white[0]
