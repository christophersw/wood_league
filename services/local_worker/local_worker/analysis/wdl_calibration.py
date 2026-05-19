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
