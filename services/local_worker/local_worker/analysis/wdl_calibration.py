"""
Title: wdl_calibration.py — lc0 WDL rescale/contempt port + draw-aware classify
Description:
    Verbatim Python port of lc0's WDL rescale/contempt transform
    (pinned lc0 commit d8ce48258c39d331c119f8c8729374ceb3df8409) plus a
    two-axis draw-aware move classifier. Pure, dependency-light, vendored
    byte-identically into the worker and the Django app; the shared
    wdl_calibration_vectors.json fixture is the cross-service contract.
Changelog:
    2026-05-19: Initial creation (issue #159).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

F32 = np.float32


def _f32(x) -> "np.float32":
    """Coerce to IEEE-754 binary32, matching lc0's float arithmetic."""
    return np.float32(x)


def fast_log2(a: "np.float32") -> float:
    """Port of lc0 FastLog2 (bit-trick log2 approximation).

    Args:
        a: positive float32.
    Returns:
        Approximate log2(a) as float.
    """
    a = _f32(a)
    tmp = struct.unpack("<I", struct.pack("<f", float(a)))[0]
    expb = tmp >> 23
    tmp = (tmp & 0x7FFFFF) | (0x7F << 23)
    out = _f32(struct.unpack("<f", struct.pack("<I", tmp))[0])
    out = _f32(out - _f32(1.0))
    return float(
        _f32(out * _f32(_f32(1.3465552) - _f32(_f32(0.34655523) * out)))
        - _f32(127)
        + _f32(expb)
    )


def fast_exp2(a: "np.float32") -> "np.float32":
    """Port of lc0 FastExp2 (bit-trick 2**x approximation).

    Args:
        a: float32 exponent.
    Returns:
        Approximate 2**a as float32.
    """
    a = _f32(a)
    if a < 0:
        if a < -126:
            return _f32(0.0)
        exp = int(np.float32(a) - np.float32(1.0))
    else:
        exp = int(np.int32(a))
    out = _f32(_f32(a) - _f32(exp))
    out = _f32(_f32(1.0) + _f32(out * _f32(_f32(0.6602339) + _f32(_f32(0.33976606) * out))))
    tmp = struct.unpack("<i", struct.pack("<f", float(out)))[0]
    tmp = (tmp + (exp << 23)) & 0xFFFFFFFF
    return _f32(struct.unpack("<f", struct.pack("<I", tmp))[0])


def fast_log(a: "np.float32") -> float:
    """Port of lc0 FastLog (natural log via FastLog2).

    Args:
        a: positive float32.
    Returns:
        Approximate ln(a) as float.
    """
    return float(_f32(0.6931471805599453) * _f32(fast_log2(a)))


def fast_exp(a: "np.float32") -> "np.float32":
    """Port of lc0 FastExp (exp via FastExp2).

    Args:
        a: float32 exponent.
    Returns:
        Approximate e**a as float32.
    """
    return fast_exp2(_f32(_f32(1.442695040) * _f32(a)))


def fast_logistic(a: "np.float32") -> "np.float32":
    """Port of lc0 FastLogistic (safeguarded logistic via FastExp).

    Args:
        a: float32 input.
    Returns:
        Approximate sigmoid(a) as float32, clamped at ±20.
    """
    a = _f32(a)
    if a > 20.0:
        return _f32(1.0)
    if a < -20.0:
        return _f32(0.0)
    return _f32(_f32(1.0) / _f32(_f32(1.0) + fast_exp(_f32(-a))))


def convert_regular_to_game_pair_elo(elo_regular: float) -> float:
    """Verbatim port of lc0 ConvertRegularToGamePairElo.

    Args:
        elo_regular: a player's regular Elo.
    Returns:
        Internally-used game-pair Elo (float).
    """
    e = _f32(elo_regular)
    transition_sharpness = _f32(250.0)
    transition_midpoint = _f32(2737.0)
    return float(
        e
        + _f32(_f32(0.5) * transition_sharpness)
        * _f32(_f32(np.log(_f32(1.0) + _f32(np.exp((transition_midpoint - e) / transition_sharpness)))))
    )


def simplified_wdl_rescale_params(
    contempt: float,
    draw_rate_reference: float,
    elo_active: float,
    contempt_max: float = 420.0,
    contempt_attenuation: float = 1.0,
) -> tuple[float, float]:
    """Verbatim port of lc0 SimplifiedWDLRescaleParams.

    Args:
        contempt: WhiteElo - BlackElo (signed).
        draw_rate_reference: measured per-network reference draw rate.
        elo_active: WDLCalibrationElo (White's Elo).
        contempt_max: ContemptMaxValue (default 420).
        contempt_attenuation: WDLContemptAttenuation (default 1.0).
    Returns:
        (wdl_rescale_ratio, wdl_rescale_diff).
    """
    scale_zero = _f32(15.0)
    elo_slope = _f32(425.0)
    offset = _f32(6.75)
    drr = _f32(draw_rate_reference)
    scale_reference = _f32(_f32(1.0) / _f32(np.log((_f32(1.0) + drr) / (_f32(1.0) - drr))))
    cmax = _f32(contempt_max)
    clamped = _f32(min(max(_f32(contempt), -cmax), cmax))
    elo_active_f = _f32(elo_active)
    elo_opp = _f32(elo_active_f - clamped)
    elo_active_g = _f32(convert_regular_to_game_pair_elo(float(elo_active_f)))
    elo_opp_g = _f32(convert_regular_to_game_pair_elo(float(elo_opp)))
    scale_active = _f32(_f32(1.0) / (_f32(_f32(1.0) / scale_zero)
                    + _f32(np.exp(elo_active_g / elo_slope - offset))))
    scale_opp = _f32(_f32(1.0) / (_f32(_f32(1.0) / scale_zero)
                 + _f32(np.exp(elo_opp_g / elo_slope - offset))))
    scale_target = _f32(_f32(np.sqrt(
        (scale_active * scale_active + scale_opp * scale_opp) / _f32(2.0))))
    ratio = _f32(scale_target / scale_reference)
    ln10 = _f32(_f32(np.log(_f32(10.0))))
    mu_active = _f32(-ln10 / _f32(200.0) * scale_zero * elo_slope
        * _f32(np.log(_f32(1.0) + _f32(np.exp(-elo_active_g / elo_slope + offset)) / scale_zero)))
    mu_opp = _f32(-ln10 / _f32(200.0) * scale_zero * elo_slope
        * _f32(np.log(_f32(1.0) + _f32(np.exp(-elo_opp_g / elo_slope + offset)) / scale_zero)))
    diff = _f32(_f32(_f32(1.0) / (scale_reference * scale_reference))
        * (mu_active - mu_opp) * _f32(contempt_attenuation))
    return float(ratio), float(diff)


@dataclass(frozen=True)
class RescaledWDL:
    """Result of rescaling one position's WDL.

    Attributes:
        wdl_white: (win, draw, loss) permille from White's frame, post-rescale.
        mu: WDL_mu returned by the rescale (side-to-move frame; 0.0 when the
            eps-guard skipped the transform).
    """
    wdl_white: tuple[int, int, int]
    mu: float


def _wdl_rescale(v: float, d: float, ratio: float, diff: float,
                 sign: float, invert: bool, max_reasonable_s: float):
    """Verbatim port of lc0 WDLRescale. Returns (mu_new, v_new, d_new).

    v and d are returned rather than mutated. Returns (0.0, v, d) unchanged
    when the eps-guard rejects an extreme distribution (lc0 `return 0`).
    """
    vf = _f32(v)
    df = _f32(d)
    rescale_diff = _f32(diff)
    rescale_ratio = _f32(ratio)
    if invert:
        rescale_diff = _f32(-rescale_diff)
        rescale_ratio = _f32(_f32(1.0) / rescale_ratio)
    w = _f32((_f32(1.0) + vf - df) / _f32(2.0))
    loss = _f32((_f32(1.0) - vf - df) / _f32(2.0))
    eps = _f32(0.0001)
    one = _f32(1.0)
    if not (w > eps and df > eps and loss > eps
            and w < (one - eps) and df < (one - eps) and loss < (one - eps)):
        return 0.0, float(vf), float(df)
    a = _f32(fast_log(_f32(_f32(1.0) / loss - _f32(1.0))))
    b = _f32(fast_log(_f32(_f32(1.0) / w - _f32(1.0))))
    s = _f32(_f32(2.0) / _f32(a + b))
    mrs = _f32(max_reasonable_s)
    if not invert:
        s = _f32(min(mrs, s))
    mu = _f32(_f32(a - b) / _f32(a + b))
    s_new = _f32(s * rescale_ratio)
    if invert:
        s, s_new = s_new, s
        s = _f32(min(mrs, s))
    mu_new = _f32(mu + _f32(_f32(sign) * s * s * rescale_diff))
    w_new = fast_logistic(_f32((_f32(-1.0) + mu_new) / s_new))
    loss_new = fast_logistic(_f32((_f32(-1.0) - mu_new) / s_new))
    v_new = _f32(w_new - loss_new)
    d_new = _f32(max(_f32(0.0), _f32(_f32(1.0) - w_new - loss_new)))
    return float(mu_new), float(v_new), float(d_new)


def rescale_wdl(
    raw_win: int, raw_draw: int, raw_loss: int, *,
    white_elo: float, black_elo: float, white_to_move: bool,
    draw_rate_reference: float,
    contempt_max: float = 420.0,
    contempt_attenuation: float = 1.0,
    wdl_max_s: float = 1.4,
) -> RescaledWDL:
    """Rescale a raw White-frame WDL triple to the players' Elo.

    Replicates lc0 with WDLCalibrationElo=White Elo, Contempt=White-Black,
    ContemptMode=white_side_analysis, WDLEvalObjectivity=1.0. Mirrors lc0's
    raw-NN-eval calibration path (src/search/classic/search.cc:2174-2186,
    SearchWorker::FetchSingleNodeResult): WDLRescale on the raw network
    (q,d) with invert=False — NOT the UCI-display path at L307
    (invert=True). A5's lc0 oracle is the binding correctness check.

    Args:
        raw_win/raw_draw/raw_loss: raw network permille, White's frame.
        white_elo/black_elo: player ratings.
        white_to_move: side to move at this position.
        draw_rate_reference: measured per-network reference draw rate.
        contempt_max/contempt_attenuation/wdl_max_s: lc0 option values.
    Returns:
        RescaledWDL (White-frame permille + mu).
    """
    total = raw_win + raw_draw + raw_loss
    if total <= 0:
        return RescaledWDL((raw_win, raw_draw, raw_loss), 0.0)
    if white_to_move:
        w, d, loss = raw_win / total, raw_draw / total, raw_loss / total
    else:
        w, d, loss = raw_loss / total, raw_draw / total, raw_win / total
    v = w - loss
    contempt = float(white_elo) - float(black_elo)
    ratio, diff = simplified_wdl_rescale_params(
        contempt, draw_rate_reference, float(white_elo),
        contempt_max, contempt_attenuation)
    # lc0 search.cc:2178-2180 raw-eval path: at depth 0,
    # sign = root_stm = (white_side_analysis ⇒ +1 white-to-move, -1 black)
    sign = 1.0 if white_to_move else -1.0
    mu, v_new, d_new = _wdl_rescale(v, d, ratio, diff, sign, False, wdl_max_s)
    w_stm = (1.0 + v_new - d_new) / 2.0
    loss_stm = (1.0 - v_new - d_new) / 2.0
    if white_to_move:
        wf_w, wf_d = w_stm, d_new
    else:
        wf_w, wf_d = loss_stm, d_new
    pw = max(0, min(1000, round(wf_w * 1000)))
    pd = max(0, min(1000, round(wf_d * 1000)))
    pl = max(0, 1000 - pw - pd)
    return RescaledWDL((pw, pd, pl), float(mu))


@dataclass(frozen=True)
class DrawAwareClass:
    """Two-axis classification of a move.

    Attributes:
        base: severity tier — Best/Excellent/Good/Inaccuracy/Mistake/Blunder.
        modifier: draw-character overlay or None
            (Missed Win/Losing Blunder/Risky/Simplification).
        counter_bucket: which Lc0GameAnalysis per-side counter this move
            increments — 'blunders'/'mistakes'/'inaccuracies'/None.
    """
    base: str
    modifier: Optional[str]
    counter_bucket: Optional[str]


def classify_draw_aware(delta_mu: float, delta_d: float) -> DrawAwareClass:
    """Canonical draw-aware classifier (spec §C4, verbatim gates).

    Args:
        delta_mu: mu_before - mu_after on the rescaled 0..1 scale
            (>0 = winning chances lost).
        delta_d: D_after - D_before (>0 = more drawish).
    Returns:
        DrawAwareClass(base, modifier, counter_bucket).
    """
    if delta_mu <= 0.01:
        base = "Best"
    elif delta_mu <= 0.02:
        base = "Excellent"
    elif delta_mu <= 0.05:
        base = "Good"
    elif delta_mu <= 0.10:
        base = "Inaccuracy"
    elif delta_mu <= 0.20:
        base = "Mistake"
    else:
        base = "Blunder"

    modifier: Optional[str] = None
    if delta_mu > 0.10 and delta_d > 0.20:
        modifier = "Missed Win"
    elif delta_mu > 0.20 and delta_d < -0.05:
        modifier = "Losing Blunder"
    elif delta_mu <= 0.05 and delta_d < -0.20:
        modifier = "Risky"
    elif delta_mu <= 0.05 and delta_d > 0.20:
        modifier = "Simplification"

    bucket = {
        "Blunder": "blunders", "Mistake": "mistakes",
        "Inaccuracy": "inaccuracies",
    }.get(base)
    return DrawAwareClass(base, modifier, bucket)
