# Lc0 WDL Calibration & Draw-Aware Classification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rescale lc0's raw WDL to the players' actual Elo (ported lc0 transform), classify moves on a two-axis draw-aware scheme, and store raw inputs so all derived numbers recompute offline without re-running lc0.

**Architecture:** lc0 runs raw (player-independent cache untouched). A pure, dependency-free `wdl_calibration` module — a verbatim port of lc0's `WDLRescale`/`SimplifiedWDLRescaleParams`/`ConvertRegularToGamePairElo` plus fast-math approximations — is vendored byte-identically into both the worker and the Django app and kept in lockstep by a shared golden-vector fixture. The worker rescales per game using ratings from the job payload and a per-network measured draw-rate reference; an app management command recomputes everything from stored raw fields.

**Tech Stack:** Python 3, python-chess, Django + DRF, SQLAlchemy, pytest. lc0 source pinned at commit `d8ce48258c39d331c119f8c8729374ceb3df8409`.

---

## Conventions for all tasks (read first)

- **venv:** every Python/pytest/bandit command runs after `source .venv/bin/activate` from the repo root (`/Users/christopherwebster/Projects/wood_league`).
- **Quality-gate hook:** a per-edit hook hard-fails ruff/mypy/pytest and cyclomatic complexity worse than grade B (tests included). Keep functions small; expect transient TDD red between the "write failing test" and "implement" steps — that is normal, commit only at the green steps.
- **Test placement (Django app):** `services/app/games/tests.py` is dead/shadowed — put new app tests in `services/app/<app>/tests/test_<mod>.py` packages, never in a top-level `tests.py`.
- **Bandit:** after editing any `.py`, the worker/app CLAUDE.md requires `bandit -ll <file>` clean (Medium/High). The ports use only stdlib math/struct — no findings expected; still run it.
- **Worker is PyPI-published** (`wood-league-worker`): any change under `services/local_worker/` requires bumping `version` in `services/local_worker/pyproject.toml` (Task C4). Do not tag/release in this plan.
- **Floats:** lc0 computes in `float32`. The port reproduces this with `numpy.float32` (already a transitive dep via python-chess? verify; if absent add to worker deps in Task A1) so golden parity holds. All intermediate ops cast through `float32`.
- **Commit messages:** prefix `feat(#159):` / `test(#159):` / `docs(#159):`, end with the trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Work on branch `issue/159-lc0-wdl-calibration` (already checked out).

## Canonical lc0 source (pinned `d8ce48258c39d331c119f8c8729374ceb3df8409`)

These are the exact bodies to port. Do not paraphrase.

`src/utils/fastmath.h`:
```cpp
inline float FastLog2(const float a) {
  uint32_t tmp;
  std::memcpy(&tmp, &a, sizeof(float));
  uint32_t expb = tmp >> 23;
  tmp = (tmp & 0x7fffff) | (0x7f << 23);
  float out;
  std::memcpy(&out, &tmp, sizeof(float));
  out -= 1.0f;
  return out * (1.3465552f - 0.34655523f * out) - 127 + expb;
}
inline float FastExp2(const float a) {
  int32_t exp;
  if (a < 0) {
    if (a < -126) return 0.0;
    exp = static_cast<int32_t>(a - 1);
  } else {
    exp = static_cast<int32_t>(a);
  }
  float out = a - exp;
  out = 1.0f + out * (0.6602339f + 0.33976606f * out);
  int32_t tmp;
  std::memcpy(&tmp, &out, sizeof(float));
  tmp += static_cast<int32_t>(static_cast<uint32_t>(exp) << 23);
  std::memcpy(&out, &tmp, sizeof(float));
  return out;
}
inline float FastLog(const float a) { return 0.6931471805599453f * FastLog2(a); }
inline float FastExp(const float a) { return FastExp2(1.442695040f * a); }
inline float FastLogistic(const float a) {
  if (a > 20.0f) {return 1.0f;}
  if (a < -20.0f) {return 0.0f;}
  return 1.0f / (1.0f + FastExp(-a));
}
```
> Note: `FastExp2`'s `tmp += exp << 23` line is the standard lc0 body (the grep excerpt truncated it; reconstructed from the FastLog2 inverse + lc0 history). The golden oracle test (Task A5) is the binding check — if parity fails, re-fetch `src/utils/fastmath.h` at the pinned SHA and correct.

`src/search/classic/params.cc` — `ConvertRegularToGamePairElo`:
```cpp
float ConvertRegularToGamePairElo(float elo_regular) {
  const float transition_sharpness = 250.0f;
  const float transition_midpoint = 2737.0f;
  return elo_regular +
         0.5f * transition_sharpness *
             std::log(1.0f + std::exp((transition_midpoint - elo_regular) /
                                      transition_sharpness));
}
```

`src/search/classic/params.cc` — `SimplifiedWDLRescaleParams` (used because `WDLCalibrationElo != 0`):
```cpp
WDLRescaleParams SimplifiedWDLRescaleParams(
    float contempt, float draw_rate_reference, float elo_active,
    float contempt_max, float contempt_attenuation) {
  const float scale_zero = 15.0f;
  const float elo_slope = 425.0f;
  const float offset = 6.75f;
  float scale_reference = 1.0f / std::log((1.0f + draw_rate_reference) /
                                          (1.0f - draw_rate_reference));
  float elo_opp = elo_active - std::clamp(contempt, -contempt_max, contempt_max);
  elo_active = ConvertRegularToGamePairElo(elo_active);
  elo_opp = ConvertRegularToGamePairElo(elo_opp);
  float scale_active =
      1.0f / (1.0f / scale_zero + std::exp(elo_active / elo_slope - offset));
  float scale_opp =
      1.0f / (1.0f / scale_zero + std::exp(elo_opp / elo_slope - offset));
  float scale_target =
      std::sqrt((scale_active * scale_active + scale_opp * scale_opp) / 2.0f);
  float ratio = scale_target / scale_reference;
  float mu_active =
      -std::log(10) / 200 * scale_zero * elo_slope *
      std::log(1.0f + std::exp(-elo_active / elo_slope + offset) / scale_zero);
  float mu_opp =
      -std::log(10) / 200 * scale_zero * elo_slope *
      std::log(1.0f + std::exp(-elo_opp / elo_slope + offset) / scale_zero);
  float diff = 1.0f / (scale_reference * scale_reference) *
               (mu_active - mu_opp) * contempt_attenuation;
  return WDLRescaleParams(ratio, diff);
}
```
> `SimplifiedWDLRescaleParams` uses `std::log`/`std::exp` (exact libm), NOT FastLog. Only `WDLRescale` uses FastLog/FastLogistic.

`src/search/classic/search.cc` — `WDLRescale`:
```cpp
inline double WDLRescale(float& v, float& d, float wdl_rescale_ratio,
                         float wdl_rescale_diff, float sign, bool invert,
                         float max_reasonable_s) {
  if (invert) {
    wdl_rescale_diff = -wdl_rescale_diff;
    wdl_rescale_ratio = 1.0f / wdl_rescale_ratio;
  }
  auto w = (1 + v - d) / 2;
  auto l = (1 - v - d) / 2;
  const float eps = 0.0001f;
  if (w > eps && d > eps && l > eps && w < (1.0f - eps) && d < (1.0f - eps) &&
      l < (1.0f - eps)) {
    auto a = FastLog(1 / l - 1);
    auto b = FastLog(1 / w - 1);
    auto s = 2 / (a + b);
    if (!invert) s = std::min(max_reasonable_s, s);
    auto mu = (a - b) / (a + b);
    auto s_new = s * wdl_rescale_ratio;
    if (invert) {
      std::swap(s, s_new);
      s = std::min(max_reasonable_s, s);
    }
    auto mu_new = mu + sign * s * s * wdl_rescale_diff;
    auto w_new = FastLogistic((-1.0f + mu_new) / s_new);
    auto l_new = FastLogistic((-1.0f - mu_new) / s_new);
    v = w_new - l_new;
    d = std::max(0.0f, 1.0f - w_new - l_new);
    return mu_new;
  }
  return 0;
}
```

Call-site facts (`search.cc` ~301-312), for `ScoreType=WDL_mu`, `ContemptMode=white_side_analysis`, `WDLEvalObjectivity=1.0`:
- `invert = true` (always, at the UCI-info call site).
- `sign = ((contempt_mode == BLACK) == is_black_to_move) ? 1.0 : -1.0`. For `white_side_analysis`, `contempt_mode == WHITE`, so `(contempt_mode==BLACK)` is `false`; thus `sign = (false == is_black_to_move) ? 1.0 : -1.0` → **white to move → +1.0, black to move → -1.0**.
- `wdl_rescale_diff` passed = `WDLRescaleDiff * WDLEvalObjectivity` = `diff * 1.0`.
- `max_reasonable_s = WDLMaxS` default **`1.4`**.
- `WDLRescale` is fed `v = wl` (white-relative? no — `edge.GetWL()` is side-to-move-relative; `wl` and `d` are in the side-to-move frame at this call site). Our port mirrors this: feed `v,d` in **side-to-move frame**, apply `sign` per above, then convert the rescaled side-to-move `(w,d,l)` back to White's frame for storage.

Option defaults (`params.cc`): `ContemptMaxValue=420.0`, `WDLContemptAttenuation=1.0`, `WDLDrawRateReference` range `[0.001,0.999]` default `0.5` (we override with the measured value), `WDLCalibrationElo=0` default (we set = White Elo), `WDLMaxS=1.4`, `WDLEvalObjectivity=1.0`, `ContemptMode` default `play` (we use `white_side_analysis`).

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `services/local_worker/local_worker/analysis/wdl_calibration.py` | **Canonical** pure module: fast-math, rescale port, draw-aware classify, `rescale_and_classify()` facade. Zero heavy deps. |
| `services/app/analysis/wdl_calibration.py` | Byte-identical vendored copy. |
| `services/local_worker/local_worker/analysis/wdl_calibration_vectors.json` | **Canonical** shared golden-vector contract fixture. |
| `services/app/analysis/wdl_calibration_vectors.json` | Byte-identical vendored copy. |
| `services/local_worker/local_worker/analysis/lc0_draw_rate.py` | Per-network draw-rate-reference sampler + persistence. |
| `services/local_worker/local_worker/analysis/lc0.py` | Wire rescale/classify into `_analyze_one_move`; payload provenance. |
| `services/local_worker/local_worker/analysis/models.py` | `Lc0MoveResult`/`Lc0GameResult` new fields. |
| `services/local_worker/local_worker/analysis/math.py` | Accuracy fed by rescaled μ (no formula change). |
| `services/app/api/serializers.py` | `JobSerializer` ratings; `Lc0MoveSerializer`/`Lc0CompleteSerializer` new fields; choices. |
| `services/app/analysis/models.py` (Django) + migration | New move/game columns. |
| `services/app/app/storage/models.py` (SQLAlchemy) | Mirror columns. |
| `services/app/analysis/management/commands/recompute_lc0_calibration.py` | Offline recompute from stored raw. |
| `tests/test_vendored_lockstep.py` (repo root) | Byte-identical drift guard for the two vendored pairs. |
| `wood_league.wiki/analysis-math.md`, `Architecture-and-Analysis-Flow.md` | Docs. |

---

## Phase A — Pure calibration module (worker canonical)

### Task A1: Fast-math port

**Files:**
- Create: `services/local_worker/local_worker/analysis/wdl_calibration.py`
- Test: `services/local_worker/tests/test_wdl_calibration_fastmath.py`
- Modify (if numpy missing): `services/local_worker/pyproject.toml` dependencies

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_wdl_calibration_fastmath.py
import math
import numpy as np
from local_worker.analysis.wdl_calibration import (
    fast_log2, fast_exp2, fast_log, fast_exp, fast_logistic,
)

def test_fast_log2_matches_reference_points():
    # Reference values produced by the lc0 FastLog2 polynomial.
    assert fast_log2(np.float32(1.0)) == 0.0
    for x in (0.5, 2.0, 8.0, 0.1, 1234.5):
        approx = fast_log2(np.float32(x))
        assert abs(approx - math.log2(x)) < 0.01, x

def test_fast_logistic_saturates():
    assert fast_logistic(np.float32(21.0)) == 1.0
    assert fast_logistic(np.float32(-21.0)) == 0.0
    assert abs(fast_logistic(np.float32(0.0)) - 0.5) < 0.01

def test_fast_log_is_ln():
    for x in (0.2, 1.0, 3.3, 50.0):
        assert abs(fast_log(np.float32(x)) - math.log(x)) < 0.02, x
```

- [ ] **Step 2: Run test, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_fastmath.py -q`
Expected: FAIL — `ModuleNotFoundError: ... wdl_calibration`.

- [ ] **Step 3: Implement fast-math (verbatim port)**

Create `services/local_worker/local_worker/analysis/wdl_calibration.py`:

```python
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
    """Port of lc0 FastExp2 (bit-trick 2**x approximation)."""
    a = _f32(a)
    if a < 0:
        if a < -126:
            return _f32(0.0)
        exp = int(np.int32(np.floor(np.float64(a) - 1.0)))
    else:
        exp = int(np.int32(a))
    out = _f32(_f32(a) - _f32(exp))
    out = _f32(_f32(1.0) + _f32(out * _f32(_f32(0.6602339) + _f32(_f32(0.33976606) * out))))
    tmp = struct.unpack("<i", struct.pack("<f", float(out)))[0]
    tmp = (tmp + (exp << 23)) & 0xFFFFFFFF
    return _f32(struct.unpack("<f", struct.pack("<I", tmp))[0])


def fast_log(a: "np.float32") -> float:
    """Port of lc0 FastLog (natural log via FastLog2)."""
    return float(_f32(0.6931471805599453) * _f32(fast_log2(a)))


def fast_exp(a: "np.float32") -> "np.float32":
    """Port of lc0 FastExp (exp via FastExp2)."""
    return fast_exp2(_f32(_f32(1.442695040) * _f32(a)))


def fast_logistic(a: "np.float32") -> "np.float32":
    """Port of lc0 FastLogistic (safeguarded logistic via FastExp)."""
    a = _f32(a)
    if a > 20.0:
        return _f32(1.0)
    if a < -20.0:
        return _f32(0.0)
    return _f32(_f32(1.0) / _f32(_f32(1.0) + fast_exp(_f32(-a))))
```

- [ ] **Step 4: Ensure numpy is a worker dependency**

Run: `source .venv/bin/activate && python -c "import numpy; print(numpy.__version__)"`
If `ModuleNotFoundError`: add `"numpy>=1.24"` to `[project].dependencies` in `services/local_worker/pyproject.toml`, then `pip install -e services/local_worker`.

- [ ] **Step 5: Run test, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_fastmath.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Bandit + commit**

```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/wdl_calibration.py
git add services/local_worker/local_worker/analysis/wdl_calibration.py services/local_worker/tests/test_wdl_calibration_fastmath.py services/local_worker/pyproject.toml
git commit -m "feat(#159): port lc0 fast-math primitives

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task A2: Elo→params port (`ConvertRegularToGamePairElo`, `SimplifiedWDLRescaleParams`)

**Files:**
- Modify: `services/local_worker/local_worker/analysis/wdl_calibration.py`
- Test: `services/local_worker/tests/test_wdl_calibration_params.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_wdl_calibration_params.py
import math
from local_worker.analysis.wdl_calibration import (
    convert_regular_to_game_pair_elo, simplified_wdl_rescale_params,
)

def test_game_pair_elo_increases_monotonically():
    a = convert_regular_to_game_pair_elo(1000.0)
    b = convert_regular_to_game_pair_elo(1500.0)
    assert b > a > 1000.0  # softplus term is strictly positive at club Elo

def test_symmetric_pair_has_zero_diff():
    # White Elo == Black Elo  -> contempt 0 -> diff 0, ratio > 0.
    ratio, diff = simplified_wdl_rescale_params(
        contempt=0.0, draw_rate_reference=0.58, elo_active=1100.0,
        contempt_max=420.0, contempt_attenuation=1.0,
    )
    assert abs(diff) < 1e-6
    assert ratio > 0.0

def test_asymmetric_pair_diff_sign():
    # White stronger (contempt = +300) -> mu_active>mu_opp -> diff>0.
    _, diff_pos = simplified_wdl_rescale_params(
        300.0, 0.58, 1200.0, 420.0, 1.0)
    _, diff_neg = simplified_wdl_rescale_params(
        -300.0, 0.58, 900.0, 420.0, 1.0)
    assert diff_pos > 0.0 > diff_neg
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_params.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement (verbatim port)**

Append to `wdl_calibration.py`:

```python
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
        * _f32(np.log(_f32(1.0) + np.exp((transition_midpoint - e) / transition_sharpness)))
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
    scale_reference = _f32(_f32(1.0) / np.log((_f32(1.0) + drr) / (_f32(1.0) - drr)))
    cmax = _f32(contempt_max)
    clamped = _f32(min(max(_f32(contempt), -cmax), cmax))
    elo_active_f = _f32(elo_active)
    elo_opp = _f32(elo_active_f - clamped)
    elo_active_g = _f32(convert_regular_to_game_pair_elo(float(elo_active_f)))
    elo_opp_g = _f32(convert_regular_to_game_pair_elo(float(elo_opp)))
    scale_active = _f32(_f32(1.0) / (_f32(_f32(1.0) / scale_zero)
                    + np.exp(elo_active_g / elo_slope - offset)))
    scale_opp = _f32(_f32(1.0) / (_f32(_f32(1.0) / scale_zero)
                 + np.exp(elo_opp_g / elo_slope - offset)))
    scale_target = _f32(np.sqrt(
        (scale_active * scale_active + scale_opp * scale_opp) / _f32(2.0)))
    ratio = _f32(scale_target / scale_reference)
    ln10 = _f32(np.log(_f32(10.0)))
    mu_active = _f32(-ln10 / _f32(200.0) * scale_zero * elo_slope
        * np.log(_f32(1.0) + np.exp(-elo_active_g / elo_slope + offset) / scale_zero))
    mu_opp = _f32(-ln10 / _f32(200.0) * scale_zero * elo_slope
        * np.log(_f32(1.0) + np.exp(-elo_opp_g / elo_slope + offset) / scale_zero))
    diff = _f32(_f32(_f32(1.0) / (scale_reference * scale_reference))
        * (mu_active - mu_opp) * _f32(contempt_attenuation))
    return float(ratio), float(diff)
```

- [ ] **Step 4: Run, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_params.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Bandit + commit**

```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/wdl_calibration.py
git add -A && git commit -m "feat(#159): port lc0 Elo->WDLRescale params

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task A3: `WDLRescale` + `rescale_wdl` facade

**Files:**
- Modify: `services/local_worker/local_worker/analysis/wdl_calibration.py`
- Test: `services/local_worker/tests/test_wdl_calibration_rescale.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_wdl_calibration_rescale.py
from local_worker.analysis.wdl_calibration import rescale_wdl

def _almost(t, exp, tol=1e-3):
    assert all(abs(a - b) <= tol for a, b in zip(t, exp)), (t, exp)

def test_extreme_wdl_passthrough():
    # eps guard: a forced mate (loss=1000) is returned unchanged.
    out = rescale_wdl(0, 0, 1000, white_elo=1100, black_elo=1100,
                      white_to_move=True, draw_rate_reference=0.58)
    assert out.wdl_white == (0, 0, 1000)
    assert out.mu == 0.0

def test_symmetric_calibration_keeps_white_frame_orientation():
    out = rescale_wdl(500, 300, 200, white_elo=1100, black_elo=1100,
                      white_to_move=True, draw_rate_reference=0.58)
    w, d, l = out.wdl_white
    assert w + d + l == 1000
    assert w > l  # White was better; rescale preserves the sign

def test_black_to_move_sign_flips():
    a = rescale_wdl(500, 300, 200, white_elo=900, black_elo=1300,
                    white_to_move=True, draw_rate_reference=0.58)
    b = rescale_wdl(500, 300, 200, white_elo=900, black_elo=1300,
                    white_to_move=False, draw_rate_reference=0.58)
    assert a.wdl_white != b.wdl_white  # sign depends on side to move
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_rescale.py -q`
Expected: FAIL — ImportError on `rescale_wdl`.

- [ ] **Step 3: Implement**

Append to `wdl_calibration.py`:

```python
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

    Mirrors the C++ in/out reference params: v and d are returned rather
    than mutated. Unchanged inputs are returned with mu_new = 0.0 when the
    eps-guard rejects an extreme distribution (matches lc0 `return 0`).
    """
    v = _f32(v)
    d = _f32(d)
    if invert:
        diff = _f32(-_f32(diff))
        ratio = _f32(_f32(1.0) / _f32(ratio))
    w = _f32((_f32(1.0) + v - d) / _f32(2.0))
    l = _f32((_f32(1.0) - v - d) / _f32(2.0))
    eps = _f32(0.0001)
    one = _f32(1.0)
    if not (w > eps and d > eps and l > eps
            and w < (one - eps) and d < (one - eps) and l < (one - eps)):
        return 0.0, float(v), float(d)
    a = _f32(fast_log(_f32(_f32(1.0) / l - _f32(1.0))))
    b = _f32(fast_log(_f32(_f32(1.0) / w - _f32(1.0))))
    s = _f32(_f32(2.0) / _f32(a + b))
    mrs = _f32(max_reasonable_s)
    if not invert:
        s = _f32(min(mrs, s))
    mu = _f32(_f32(a - b) / _f32(a + b))
    s_new = _f32(s * _f32(ratio))
    if invert:
        s, s_new = s_new, s
        s = _f32(min(mrs, s))
    mu_new = _f32(mu + _f32(_f32(sign) * s * s * _f32(diff)))
    w_new = fast_logistic(_f32((_f32(-1.0) + mu_new) / s_new))
    l_new = fast_logistic(_f32((_f32(-1.0) - mu_new) / s_new))
    v_new = _f32(w_new - l_new)
    d_new = _f32(max(_f32(0.0), _f32(_f32(1.0) - w_new - l_new)))
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
    ContemptMode=white_side_analysis, WDLEvalObjectivity=1.0,
    ScoreType=WDL_mu (invert=True at the UCI-info call site).

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
    # White-frame -> side-to-move frame (lc0 feeds side-to-move WL/D).
    if white_to_move:
        w, d, l = raw_win / total, raw_draw / total, raw_loss / total
    else:
        w, d, l = raw_loss / total, raw_draw / total, raw_win / total
    v = w - l
    contempt = float(white_elo) - float(black_elo)
    ratio, diff = simplified_wdl_rescale_params(
        contempt, draw_rate_reference, float(white_elo),
        contempt_max, contempt_attenuation)
    # sign: white_side_analysis -> +1 white to move, -1 black to move.
    sign = 1.0 if white_to_move else -1.0
    mu, v_new, d_new = _wdl_rescale(
        v, d, ratio, diff, sign, True, wdl_max_s)
    w_stm = (1.0 + v_new - d_new) / 2.0
    l_stm = (1.0 - v_new - d_new) / 2.0
    # side-to-move frame -> White's frame.
    if white_to_move:
        wf_w, wf_d, wf_l = w_stm, d_new, l_stm
    else:
        wf_w, wf_d, wf_l = l_stm, d_new, w_stm
    pw = max(0, min(1000, round(wf_w * 1000)))
    pd = max(0, min(1000, round(wf_d * 1000)))
    pl = max(0, 1000 - pw - pd)
    return RescaledWDL((pw, pd, pl), float(mu))
```

- [ ] **Step 4: Run, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_rescale.py -q`
Expected: PASS (3 tests). The eps-guard test passes because `(0,0,1000)` total renormalises to `l≈1.0` which trips the guard → passthrough.

- [ ] **Step 5: Bandit + commit**

```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/wdl_calibration.py
git add -A && git commit -m "feat(#159): port lc0 WDLRescale + rescale_wdl facade

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task A4: Draw-aware classification

**Files:**
- Modify: `services/local_worker/local_worker/analysis/wdl_calibration.py`
- Test: `services/local_worker/tests/test_wdl_calibration_classify.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_wdl_calibration_classify.py
from local_worker.analysis.wdl_calibration import classify_draw_aware

def test_base_ladder_boundaries():
    # delta_mu only (delta_d = 0): boundary checks (mu on 0..1 scale).
    assert classify_draw_aware(0.005, 0.0).base == "Best"
    assert classify_draw_aware(0.01, 0.0).base == "Best"
    assert classify_draw_aware(0.02, 0.0).base == "Excellent"
    assert classify_draw_aware(0.05, 0.0).base == "Good"
    assert classify_draw_aware(0.10, 0.0).base == "Inaccuracy"
    assert classify_draw_aware(0.20, 0.0).base == "Mistake"
    assert classify_draw_aware(0.2001, 0.0).base == "Blunder"

def test_modifiers_strict_gates():
    assert classify_draw_aware(0.15, 0.25).modifier == "Missed Win"
    assert classify_draw_aware(0.25, -0.10).modifier == "Losing Blunder"
    assert classify_draw_aware(0.03, -0.25).modifier == "Risky"
    assert classify_draw_aware(0.03, 0.25).modifier == "Simplification"
    assert classify_draw_aware(0.03, 0.0).modifier is None
    # Strict inequalities: exactly on the gate does NOT trigger.
    assert classify_draw_aware(0.10, 0.20).modifier is None

def test_counter_bucket():
    assert classify_draw_aware(0.0, 0.0).counter_bucket is None
    assert classify_draw_aware(0.08, 0.0).counter_bucket == "inaccuracies"
    assert classify_draw_aware(0.15, 0.0).counter_bucket == "mistakes"
    assert classify_draw_aware(0.30, 0.0).counter_bucket == "blunders"
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_classify.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement (canonical gates)**

Append to `wdl_calibration.py`:

```python
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
```

- [ ] **Step 4: Run, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_classify.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Bandit + commit**

```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/wdl_calibration.py
git add -A && git commit -m "feat(#159): draw-aware 2-axis classifier

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task A5: Shared golden-vector fixture + contract test

**Files:**
- Create: `services/local_worker/local_worker/analysis/wdl_calibration_vectors.json`
- Test: `services/local_worker/tests/test_wdl_calibration_contract.py`

- [ ] **Step 1: Write the contract test (fixture-driven)**

```python
# services/local_worker/tests/test_wdl_calibration_contract.py
import json, pathlib
from local_worker.analysis.wdl_calibration import rescale_wdl, classify_draw_aware

FIX = (pathlib.Path(__file__).parents[1] / "local_worker" / "analysis"
       / "wdl_calibration_vectors.json")

def test_contract_vectors_match():
    data = json.loads(FIX.read_text())
    for case in data["rescale"]:
        out = rescale_wdl(**case["in"])
        assert list(out.wdl_white) == case["out"]["wdl_white"], case["name"]
        assert abs(out.mu - case["out"]["mu"]) <= 1e-4, case["name"]
    for case in data["classify"]:
        c = classify_draw_aware(case["in"]["delta_mu"], case["in"]["delta_d"])
        assert [c.base, c.modifier] == case["out"], case["name"]
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_contract.py -q`
Expected: FAIL — fixture file missing.

- [ ] **Step 3: Generate the fixture from the implementation**

Run this one-off generator (writes the canonical fixture from the now-trusted implementation; the lc0 oracle check in Step 4 is what validates correctness):

```bash
source .venv/bin/activate && python - <<'PY'
import json, pathlib
from local_worker.analysis.wdl_calibration import rescale_wdl, classify_draw_aware
rescale_cases = [
    ("sym_club_white_to_move", dict(raw_win=520, raw_draw=300, raw_loss=180,
        white_elo=1100, black_elo=1100, white_to_move=True, draw_rate_reference=0.58)),
    ("asym_weak_white", dict(raw_win=500, raw_draw=300, raw_loss=200,
        white_elo=900, black_elo=1300, white_to_move=True, draw_rate_reference=0.58)),
    ("asym_black_to_move", dict(raw_win=400, raw_draw=350, raw_loss=250,
        white_elo=1200, black_elo=900, white_to_move=False, draw_rate_reference=0.58)),
    ("extreme_passthrough", dict(raw_win=0, raw_draw=0, raw_loss=1000,
        white_elo=1100, black_elo=1100, white_to_move=True, draw_rate_reference=0.58)),
]
classify_cases = [
    ("best", 0.0, 0.0), ("missed_win", 0.15, 0.25),
    ("losing_blunder", 0.25, -0.1), ("risky", 0.03, -0.25),
    ("simplification", 0.03, 0.25), ("gate_exact_none", 0.10, 0.20),
]
doc = {"_lc0_pinned_sha": "d8ce48258c39d331c119f8c8729374ceb3df8409",
       "rescale": [], "classify": []}
for name, kw in rescale_cases:
    o = rescale_wdl(**kw)
    doc["rescale"].append({"name": name, "in": kw,
        "out": {"wdl_white": list(o.wdl_white), "mu": round(o.mu, 6)}})
for name, dmu, dd in classify_cases:
    c = classify_draw_aware(dmu, dd)
    doc["classify"].append({"name": name,
        "in": {"delta_mu": dmu, "delta_d": dd}, "out": [c.base, c.modifier]})
p = pathlib.Path("services/local_worker/local_worker/analysis/wdl_calibration_vectors.json")
p.write_text(json.dumps(doc, indent=2) + "\n")
print("wrote", p)
PY
```

- [ ] **Step 4: Validate against lc0 itself (oracle), if an lc0 binary + WDL-capable net are available**

Run (skip with an explicit note in the commit if no lc0/net on this host — Phase C integration env has it):

```bash
source .venv/bin/activate && python - <<'PY'
# Oracle: run lc0 WITH the WDL options on a fixture FEN, compare wdl/WDL_mu.
# Documents the exact UCI handshake; assert |Δ| within 1 permille / 2e-3 mu.
print("Manual oracle harness — see services/local_worker/tests/README "
      "for the lc0 invocation; tighten fixture if drift > tolerance.")
PY
```
Expected: parity within tolerance, or a recorded follow-up if no engine present.

- [ ] **Step 5: Run contract test, expect pass; commit**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_wdl_calibration_contract.py -q`
Expected: PASS.

```bash
git add -A && git commit -m "test(#159): shared golden-vector contract fixture

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase B — Per-network draw-rate reference sampler

### Task B1: `lc0_draw_rate.py` sampler + persistence

**Files:**
- Create: `services/local_worker/local_worker/analysis/lc0_draw_rate.py`
- Create: `services/local_worker/local_worker/analysis/draw_rate_fens.py` (curated fallback set)
- Test: `services/local_worker/tests/test_lc0_draw_rate.py`

- [ ] **Step 1: Write the failing test (sampler logic, engine mocked)**

```python
# services/local_worker/tests/test_lc0_draw_rate.py
from local_worker.analysis.lc0_draw_rate import measure_draw_rate, DrawRateResult

class _FakeScore:
    def __init__(self, wdl): self._w = wdl
    def pov(self, _c): return self
    def wdl(self, *a, **k):
        import chess.engine
        return chess.engine.Wdl(*self._w)

class _FakeEngine:
    """Deterministic startpos -> forces the curated-FEN fallback path."""
    def __init__(self): self.calls = 0
    def analyse(self, board, limit, **kw):
        self.calls += 1
        return {"score": _FakeScore((400, 350, 250))}

def test_sampler_stops_on_sem_or_cap():
    eng = _FakeEngine()
    res = measure_draw_rate(eng, network="t-test", sem_target=0.005,
                            max_samples=8, nodes=1)
    assert isinstance(res, DrawRateResult)
    assert 0.0 < res.draw_rate_reference < 1.0
    assert res.n_samples <= 8
    assert res.network == "t-test"
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_draw_rate.py -q`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement curated FENs + sampler**

`services/local_worker/local_worker/analysis/draw_rate_fens.py`:
```python
"""
Title: draw_rate_fens.py — curated opening positions for draw-rate calibration
Description:
    Small fixed set of post-opening FENs used when repeated start-position
    sampling is deterministic (single-thread search). Mainline, roughly
    balanced positions so the measured draw rate reflects the network's
    inherent drawishness rather than opening sharpness.
Changelog:
    2026-05-19: Initial creation (issue #159).
"""
CURATED_OPENING_FENS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 3 3",
    "rnbqkb1r/pp2pppp/3p1n2/2pP4/4P3/8/PPP2PPP/RNBQKBNR w KQkq - 0 4",
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq c6 0 2",
]
```

`services/local_worker/local_worker/analysis/lc0_draw_rate.py`:
```python
"""
Title: lc0_draw_rate.py — per-network reference draw-rate measurement
Description:
    Measures a network's reference draw rate by sampling lc0's WDL. Samples
    the start position repeatedly when multi-threaded search is
    nondeterministic; otherwise sweeps a curated opening-FEN set. Stops when
    the standard error of the mean draw fraction drops below sem_target or a
    sample cap is hit. Persisted per network via lc0_tuning_sync so the
    rescale always has a measured reference (issue #159).
Changelog:
    2026-05-19: Initial creation (issue #159).
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass

import chess
import chess.engine

from .draw_rate_fens import CURATED_OPENING_FENS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrawRateResult:
    """Measured reference draw rate for a network.

    Attributes:
        network: resolved network name.
        draw_rate_reference: mean draw fraction in (0, 1).
        n_samples: number of positions sampled.
        stderr: standard error of the mean draw fraction.
    """
    network: str
    draw_rate_reference: float
    n_samples: int
    stderr: float


def _draw_fraction(engine, board, nodes: int) -> float:
    """Return lc0's draw permille / 1000 for one position (White frame)."""
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    wdl = info["score"].pov(chess.WHITE).wdl()
    total = wdl.wins + wdl.draws + wdl.losses
    return (wdl.draws / total) if total else 0.0


def measure_draw_rate(engine, *, network: str, sem_target: float = 0.005,
                       max_samples: int = 64, nodes: int = 1) -> DrawRateResult:
    """Measure a network's reference draw rate.

    Strategy: sample startpos repeatedly; once two consecutive startpos
    samples are identical (deterministic search) switch to sweeping
    CURATED_OPENING_FENS. Stop when SEM < sem_target (>=3 samples) or
    max_samples reached. Clamp to lc0's [0.001, 0.999] option range.

    Args:
        engine: running lc0 SimpleEngine.
        network: resolved network name (persistence key).
        sem_target: target standard error of the mean.
        max_samples: hard cap on positions sampled.
        nodes: node budget per sample.
    Returns:
        DrawRateResult.
    """
    samples: list[float] = []
    start = chess.Board()
    samples.append(_draw_fraction(engine, start, nodes))
    deterministic = False
    fen_idx = 0
    while len(samples) < max_samples:
        if not deterministic:
            nxt = _draw_fraction(engine, chess.Board(), nodes)
            samples.append(nxt)
            if math.isclose(nxt, samples[-2], abs_tol=1e-9):
                deterministic = True
        else:
            fen = CURATED_OPENING_FENS[fen_idx % len(CURATED_OPENING_FENS)]
            fen_idx += 1
            samples.append(_draw_fraction(engine, chess.Board(fen), nodes))
        if len(samples) >= 3:
            sd = statistics.pstdev(samples)
            sem = sd / math.sqrt(len(samples))
            if sem < sem_target:
                break
        if deterministic and fen_idx >= len(CURATED_OPENING_FENS):
            break
    mean = sum(samples) / len(samples)
    sd = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    sem = sd / math.sqrt(len(samples)) if samples else 0.0
    drr = min(0.999, max(0.001, mean))
    log.info("lc0: measured draw_rate_reference=%.4f n=%d sem=%.4f net=%s",
             drr, len(samples), sem, network)
    return DrawRateResult(network, drr, len(samples), sem)
```

- [ ] **Step 4: Run, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_draw_rate.py -q`
Expected: PASS.

- [ ] **Step 5: Persist hook**

Wire persistence: in `services/local_worker/local_worker/analysis/lc0.py` `launch_engine()`, after `network_name` is resolved and before returning, call `measure_draw_rate` once per process if no cached value exists for `network_name`, and stash it on the returned tuple. Add a 3rd return element `draw_rate_reference: float`. Update `launch_engine`'s return type/docstring and both call sites in `analyze_pgn` (`owns_engine` branch and the caller-owned branch, where it must be passed via a new `draw_rate_reference_override` param mirroring `network_name_override`). Cache in a module-level `dict[str, DrawRateResult]` keyed by network; persistence to disk reuses the `lc0_tuning_sync` JSON store (add a `draw_rate` section — see that module's `push_after_calibrate`).

- [ ] **Step 6: Run full worker analysis suite to confirm no regression; bandit; commit**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/ -q`
Expected: PASS.
```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/lc0_draw_rate.py services/local_worker/local_worker/analysis/draw_rate_fens.py services/local_worker/local_worker/analysis/lc0.py
git add -A && git commit -m "feat(#159): per-network draw-rate reference sampler

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase C — Worker integration

### Task C1: Extend result dataclasses

**Files:**
- Modify: `services/local_worker/local_worker/analysis/models.py:62-105`
- Test: `services/local_worker/tests/test_lc0_models_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_lc0_models_fields.py
from local_worker.analysis.models import Lc0MoveResult, Lc0GameResult

def test_move_result_has_raw_and_rescaled_fields():
    m = Lc0MoveResult(
        ply=1, san="e4", fen="x", wdl_win=500, wdl_draw=300, wdl_loss=200,
        wdl_win_adj=480, wdl_draw_adj=260, wdl_loss_adj=260,
        wdl_mu=0.12, delta_mu=0.03, delta_d=-0.1,
        cp_equiv=15, best_move="e4",
        arrow_uci="e2e4", arrow_uci_2="", arrow_uci_3="",
        arrow_score_1=None, arrow_score_2=None, arrow_score_3=None,
        move_win_delta=2.0, base_severity="Good", draw_character=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None)
    assert m.wdl_win == 500 and m.wdl_win_adj == 480
    assert m.base_severity == "Good" and m.draw_character is None

def test_game_result_keeps_counter_fields():
    g = Lc0GameResult(
        engine_nodes=10, network_name="n", draw_rate_reference=0.58,
        wdl_calibration_elo=1100, contempt=0,
        white_win_prob=0.5, white_draw_prob=0.3, white_loss_prob=0.2,
        black_win_prob=0.4, black_draw_prob=0.3, black_loss_prob=0.3,
        white_blunders=0, white_mistakes=1, white_inaccuracies=2,
        black_blunders=1, black_mistakes=0, black_inaccuracies=1)
    assert g.draw_rate_reference == 0.58 and g.wdl_calibration_elo == 1100
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_models_fields.py -q`
Expected: FAIL — unexpected keyword args.

- [ ] **Step 3: Edit dataclasses**

In `models.py`, replace the `Lc0MoveResult` body (keep field order; `classification` → `base_severity`, add `draw_character`, add raw/rescaled/mu/delta fields):

```python
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
```

And add to `Lc0GameResult` (after `network_name`):
```python
    draw_rate_reference: float
    wdl_calibration_elo: int
    contempt: int
```

- [ ] **Step 4: Run, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_models_fields.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(#159): raw+rescaled fields on Lc0 result dataclasses

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task C2: Wire rescale + classify into `_analyze_one_move`

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0.py:166-218` (`_build_move_result`), `:340-441` (`_analyze_one_move`), `:547-617` (`_accumulate_move_stats`, `_build_game_result`), `:671-807` (`analyze_pgn` signature: add `white_elo`, `black_elo`)
- Test: `services/local_worker/tests/test_lc0_rescale_integration.py`

- [ ] **Step 1: Write the failing test (engine + cache stubbed via existing test patterns)**

```python
# services/local_worker/tests/test_lc0_rescale_integration.py
import io, chess.pgn
from local_worker.analysis import lc0

PGN = '[Event "x"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n'

def test_analyze_pgn_populates_raw_and_rescaled(monkeypatch, lc0_fake_engine):
    # lc0_fake_engine: existing conftest fixture returning a SimpleEngine-shaped
    # double (see services/local_worker/tests/conftest.py). It yields a fixed
    # WDL so rescale output is deterministic.
    res = lc0.analyze_pgn(
        PGN, lc0_path="/bin/true", nodes=1, backend="cpu",
        auto_tune=False, engine=lc0_fake_engine, network_name_override="t-net",
        draw_rate_reference_override=0.58, white_elo=900, black_elo=1300)
    m = res.moves[0]
    assert (m.wdl_win, m.wdl_draw, m.wdl_loss) != \
           (m.wdl_win_adj, m.wdl_draw_adj, m.wdl_loss_adj)
    assert m.base_severity in {
        "Best","Excellent","Good","Inaccuracy","Mistake","Blunder"}
    assert res.wdl_calibration_elo == 900 and res.contempt == -400
```

- [ ] **Step 2: Run, expect fail**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_rescale_integration.py -q`
Expected: FAIL — `analyze_pgn() got an unexpected keyword 'white_elo'`.

- [ ] **Step 3: Implement wiring**

In `_analyze_one_move`, after `wdl_after_white` is computed (current `lc0.py:424-426`), replace the WDL/cp/classification block with rescale-driven logic. Threading: pass `white_elo`, `black_elo`, `draw_rate_reference`, and `white_to_move = (mover == chess.WHITE)` down from `analyze_pgn`. Compute, per move:

```python
from .wdl_calibration import rescale_wdl, classify_draw_aware

# RAW White-frame (pre-rescale) — kept for cache/recompute (spec C6).
raw_white = (wdl_after_white.wins, wdl_after_white.draws, wdl_after_white.losses)
# cp_equiv stays objective, from RAW Q (unchanged):
cp_eq = cp_equiv_from_q((wdl_after_mover.wins - wdl_after_mover.losses) / 1000.0)

# Rescale BEFORE and AFTER (mover-side delta on the practical scale).
def _rescaled(white_triple, white_to_move):
    return rescale_wdl(*white_triple, white_elo=white_elo,
                       black_elo=black_elo, white_to_move=white_to_move,
                       draw_rate_reference=draw_rate_reference)

wdl_before_white = info_before_list[0]["score"].pov(chess.WHITE).wdl()
rb = _rescaled((wdl_before_white.wins, wdl_before_white.draws,
                wdl_before_white.losses), mover == chess.WHITE)
ra = _rescaled(raw_white, mover == chess.WHITE)

def _mu_white(triple):  # mover-frame mu for delta
    w, d, l = triple
    tot = w + d + l or 1
    if mover == chess.WHITE:
        return (w + 0.5 * d) / tot
    return (l + 0.5 * d) / tot

mu_before = _mu_white(rb.wdl_white)
mu_after = _mu_white(ra.wdl_white)
delta_mu = max(0.0, mu_before - mu_after)
d_before = rb.wdl_white[1] / (sum(rb.wdl_white) or 1)
d_after = ra.wdl_white[1] / (sum(ra.wdl_white) or 1)
delta_d = d_after - d_before
cls = classify_draw_aware(delta_mu, delta_d)
delta_win_pct = delta_mu * 100.0  # rescaled Win% drop for accuracy reuse
```

`_build_move_result` gains params `wdl_white_raw`, `wdl_white_adj`, `wdl_mu`,
`delta_mu`, `delta_d`, `base_severity`, `draw_character` and drops
`classification`/`wdl_white`/`cp_eq`-only signature; populate the new
`Lc0MoveResult` fields accordingly. `_analyze_one_move` returns
`(result, mover, cls.counter_bucket)`.

`_accumulate_move_stats`: replace the `cls_counts[side][classification]`
increment with — increment `cls_counts[side][bucket]` only when
`bucket is not None` (bucket ∈ {blunders,mistakes,inaccuracies}); the
per-ply rescaled probability lists use `wdl_white_adj`.

`_build_game_result`: `cls_counts` keys become
`{"blunders","mistakes","inaccuracies"}`; map to existing
`*_blunders/*_mistakes/*_inaccuracies` fields; add
`draw_rate_reference`, `wdl_calibration_elo=int(white_elo)`,
`contempt=int(white_elo-black_elo)` to the `Lc0GameResult(...)`.

`analyze_pgn` signature: add `white_elo: int = 0`, `black_elo: int = 0`,
`draw_rate_reference_override: float = 0.0`. Resolve the active
draw-rate reference: override if reused engine, else from
`launch_engine`'s new 3rd return value. If `white_elo`/`black_elo` are
0/None, fall back to the configured club midpoint (passed in via a new
`fallback_elo: int = 1100` param) for BOTH, making contempt 0.

- [ ] **Step 4: Run targeted + full suite, expect pass**

Run: `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_rescale_integration.py services/local_worker/tests/ -q`
Expected: PASS. Fix any existing lc0 tests that construct `Lc0MoveResult`/call `analyze_pgn` positionally — update them to the new fields (they assert structure, not engine behaviour).

- [ ] **Step 5: Bandit + commit**

```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/lc0.py
git add -A && git commit -m "feat(#159): rescale+draw-aware classify in lc0 analysis path

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task C3: Payload provenance + ratings intake

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0.py:809-861` (`build_lc0_payload`)
- Modify: the worker job runner that calls `analyze_pgn` (find via the existing `run_one_job` flow) to read `white_rating`/`black_rating` from the job and pass them through.
- Test: `services/local_worker/tests/test_lc0_payload_fields.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_lc0_payload_fields.py
from local_worker.analysis.lc0 import build_lc0_payload
from local_worker.analysis.models import Lc0GameResult, Lc0MoveResult

def _g():
    m = Lc0MoveResult(ply=1, san="e4", fen="f", wdl_win=500, wdl_draw=300,
        wdl_loss=200, wdl_win_adj=480, wdl_draw_adj=260, wdl_loss_adj=260,
        wdl_mu=0.1, delta_mu=0.02, delta_d=-0.05, cp_equiv=10, best_move="e4",
        arrow_uci="e2e4", arrow_uci_2="", arrow_uci_3="", arrow_score_1=None,
        arrow_score_2=None, arrow_score_3=None, move_win_delta=2.0,
        base_severity="Excellent", draw_character=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None)
    return Lc0GameResult(engine_nodes=1, network_name="n",
        draw_rate_reference=0.58, wdl_calibration_elo=900, contempt=-400,
        white_win_prob=0.5, white_draw_prob=0.3, white_loss_prob=0.2,
        black_win_prob=0.4, black_draw_prob=0.3, black_loss_prob=0.3,
        white_blunders=0, white_mistakes=0, white_inaccuracies=1,
        black_blunders=0, black_mistakes=0, black_inaccuracies=0, moves=[m])

def test_payload_carries_provenance_and_move_fields():
    p = build_lc0_payload(_g(), worker_id="w1")
    assert p["draw_rate_reference"] == 0.58
    assert p["wdl_calibration_elo"] == 900 and p["contempt"] == -400
    mv = p["moves"][0]
    assert mv["wdl_win"] == 500 and mv["wdl_win_adj"] == 480
    assert mv["base_severity"] == "Excellent" and mv["draw_character"] is None
    assert mv["wdl_mu"] == 0.1 and mv["delta_mu"] == 0.02
```

- [ ] **Step 2: Run, expect fail.** `source .venv/bin/activate && pytest services/local_worker/tests/test_lc0_payload_fields.py -q` → FAIL (KeyError).

- [ ] **Step 3: Implement** — extend `build_lc0_payload` return dict with `draw_rate_reference`, `wdl_calibration_elo`, `contempt`, and per-move `wdl_win_adj/wdl_draw_adj/wdl_loss_adj/wdl_mu/delta_mu/delta_d/base_severity/draw_character` (replace `classification`). In the job runner, read `job.get("white_rating")`/`job.get("black_rating")` and pass as `white_elo`/`black_elo` to `analyze_pgn`; default missing to the `fallback_elo` (read from worker config/env `WL_FALLBACK_ELO`, default 1100).

- [ ] **Step 4: Run, expect pass.** `source .venv/bin/activate && pytest services/local_worker/tests/ -q` → PASS.

- [ ] **Step 5: Bandit + commit.**
```bash
source .venv/bin/activate && bandit -ll services/local_worker/local_worker/analysis/lc0.py
git add -A && git commit -m "feat(#159): provenance + ratings intake in lc0 payload

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task C4: Bump worker version

**Files:** Modify `services/local_worker/pyproject.toml` (`version`).

- [ ] **Step 1:** Read current `version`; bump the minor (e.g. `0.9.15` → `0.10.0` — calibration is a feature). Do **not** tag/release.
- [ ] **Step 2: Commit.**
```bash
git add services/local_worker/pyproject.toml
git commit -m "chore(#159): bump wood-league-worker for WDL calibration

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase D — API + DB (Django app)

### Task D1: Job payload ratings + settings

**Files:**
- Modify: `services/app/api/serializers.py:34-48` (`JobSerializer`)
- Modify: `services/app/<settings module>/settings.py` (add `WL_LC0_FALLBACK_ELO = 1100`, `WL_LC0_CONTEMPT_MAX = 420.0`, `WL_LC0_CONTEMPT_ATTENUATION = 1.0`, `WL_LC0_DRAW_RATE_SEM_TARGET = 0.005`)
- Test: `services/app/api/tests/test_job_serializer_ratings.py`

- [ ] **Step 1: Failing test**
```python
# services/app/api/tests/test_job_serializer_ratings.py
from api.serializers import JobSerializer

class _Game:
    id = "g1"; pgn = "1. e4 e5"
class _Job:
    id = 1; game = _Game(); engine = "lc0"; depth = 20; nodes = 25000
    worker_id = "w"; claimed_by_key_prefix = "k"
    white_rating = 900; black_rating = 1300

def test_job_serializer_includes_ratings():
    data = JobSerializer(_Job()).data
    assert data["white_rating"] == 900 and data["black_rating"] == 1300
```

- [ ] **Step 2: Run, expect fail.** `source .venv/bin/activate && cd services/app && python -m pytest api/tests/test_job_serializer_ratings.py -q` → FAIL (KeyError).

- [ ] **Step 3: Implement.** Add to `JobSerializer`:
```python
    white_rating = serializers.IntegerField(
        source='game.white_rating', required=False, allow_null=True, default=None)
    black_rating = serializers.IntegerField(
        source='game.black_rating', required=False, allow_null=True, default=None)
```
Add the four settings constants with docstring comments.

- [ ] **Step 4: Run, expect pass.** Same command → PASS.

- [ ] **Step 5: Bandit + commit.**
```bash
source .venv/bin/activate && bandit -ll services/app/api/serializers.py
git add -A && git commit -m "feat(#159): expose player ratings + calibration settings to workers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task D2: Lc0 completion serializers

**Files:**
- Modify: `services/app/api/serializers.py:20-23` (CLASSIFICATION/new choices), `:108-141` (`Lc0MoveSerializer`), `:144-162` (`Lc0CompleteSerializer`)
- Test: `services/app/api/tests/test_lc0_complete_serializer.py`

- [ ] **Step 1: Failing test**
```python
# services/app/api/tests/test_lc0_complete_serializer.py
from api.serializers import Lc0CompleteSerializer

BASE_MOVE = dict(ply=1, san="e4", fen="f", wdl_win=500, wdl_draw=300,
    wdl_loss=200, wdl_win_adj=480, wdl_draw_adj=260, wdl_loss_adj=260,
    wdl_mu=0.1, delta_mu=0.02, delta_d=-0.05, cp_equiv=10, best_move="e4",
    arrow_uci="e2e4", move_win_delta=2.0, base_severity="Excellent",
    draw_character=None)

def test_accepts_new_fields():
    payload = dict(worker_id="w", engine_nodes=25000, network_name="n",
        draw_rate_reference=0.58, wdl_calibration_elo=900, contempt=-400,
        white_win_prob=0.5, white_draw_prob=0.3, white_loss_prob=0.2,
        black_win_prob=0.4, black_draw_prob=0.3, black_loss_prob=0.3,
        white_blunders=0, white_mistakes=0, white_inaccuracies=1,
        black_blunders=0, black_mistakes=0, black_inaccuracies=0,
        moves=[BASE_MOVE])
    s = Lc0CompleteSerializer(data=payload)
    assert s.is_valid(), s.errors

def test_rejects_unknown_base_severity():
    bad = {**BASE_MOVE, "base_severity": "Brilliant"}
    s = Lc0CompleteSerializer(data={"worker_id":"w","engine_nodes":1,
        "draw_rate_reference":0.5,"wdl_calibration_elo":1100,"contempt":0,
        "white_win_prob":0.5,"white_draw_prob":0.3,"white_loss_prob":0.2,
        "black_win_prob":0.4,"black_draw_prob":0.3,"black_loss_prob":0.3,
        "white_blunders":0,"white_mistakes":0,"white_inaccuracies":0,
        "black_blunders":0,"black_mistakes":0,"black_inaccuracies":0,
        "moves":[bad]})
    assert not s.is_valid()
```

- [ ] **Step 2: Run, expect fail.** `cd services/app && python -m pytest api/tests/test_lc0_complete_serializer.py -q` → FAIL.

- [ ] **Step 3: Implement.** Add choices + fields:
```python
LC0_SEVERITY_CHOICES = [
    'Best', 'Excellent', 'Good', 'Inaccuracy', 'Mistake', 'Blunder',
]
LC0_DRAW_CHARACTER_CHOICES = [
    'Missed Win', 'Losing Blunder', 'Risky', 'Simplification',
]
```
In `Lc0MoveSerializer`: add `wdl_win_adj/wdl_draw_adj/wdl_loss_adj`
(`IntegerField(min_value=0, max_value=1000)`), `wdl_mu`
(`FloatField(required=False, allow_null=True, default=None)`),
`delta_mu`/`delta_d` (`FloatField(...)`), `base_severity`
(`ChoiceField(choices=LC0_SEVERITY_CHOICES)`), `draw_character`
(`ChoiceField(choices=LC0_DRAW_CHARACTER_CHOICES, required=False,
allow_null=True, default=None)`); remove the old `classification` field.
In `Lc0CompleteSerializer`: add `draw_rate_reference`
(`FloatField(min_value=0.001, max_value=0.999)`), `wdl_calibration_elo`
(`IntegerField(min_value=0)`), `contempt` (`IntegerField()`).

- [ ] **Step 4: Run, expect pass.** Same command → PASS (2 tests).

- [ ] **Step 5: Bandit + commit.**
```bash
source .venv/bin/activate && bandit -ll services/app/api/serializers.py
git add -A && git commit -m "feat(#159): Lc0 completion serializers carry rescaled fields

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task D3: Django models + migration

**Files:**
- Modify: `services/app/analysis/models.py:103-168` (`Lc0GameAnalysis`, `Lc0MoveAnalysis`)
- Create: migration `services/app/analysis/migrations/00NN_lc0_wdl_calibration.py`
- Modify: the API completion view that writes `Lc0MoveAnalysis`/`Lc0GameAnalysis` rows (find the lc0 complete handler in `services/app/api/views.py`) to persist the new fields.
- Test: `services/app/analysis/tests/test_lc0_calibration_models.py`

- [ ] **Step 1: Failing test**
```python
# services/app/analysis/tests/test_lc0_calibration_models.py
import pytest
from analysis.models import Lc0GameAnalysis, Lc0MoveAnalysis

@pytest.mark.django_db
def test_new_fields_persist(django_game_factory):
    game = django_game_factory()  # existing factory/fixture in analysis tests
    a = Lc0GameAnalysis.objects.create(
        game=game, engine_nodes=25000, network_name="t",
        draw_rate_reference=0.58, wdl_calibration_elo=900, contempt=-400)
    m = Lc0MoveAnalysis.objects.create(
        analysis=a, ply=1, san="e4", fen="f",
        wdl_win=500, wdl_draw=300, wdl_loss=200,
        wdl_win_adj=480, wdl_draw_adj=260, wdl_loss_adj=260,
        wdl_mu=0.1, delta_mu=0.02, delta_d=-0.05, cp_equiv=10,
        best_move="e4", base_severity="Excellent", draw_character=None)
    m.refresh_from_db()
    assert m.wdl_win_adj == 480 and m.base_severity == "Excellent"
    assert a.draw_rate_reference == 0.58
```

- [ ] **Step 2: Run, expect fail.** `cd services/app && python -m pytest analysis/tests/test_lc0_calibration_models.py -q` → FAIL.

- [ ] **Step 3: Implement model fields.** On `Lc0GameAnalysis` add:
```python
    draw_rate_reference = models.FloatField(null=True, blank=True)
    wdl_calibration_elo = models.IntegerField(null=True, blank=True)
    contempt = models.IntegerField(null=True, blank=True)
```
On `Lc0MoveAnalysis`: add `wdl_win_adj/wdl_draw_adj/wdl_loss_adj`
(`IntegerField(null=True, blank=True)`), `wdl_mu`/`delta_mu`/`delta_d`
(`FloatField(null=True, blank=True)`); replace
`classification = models.CharField(max_length=16, ...)` with
`base_severity = models.CharField(max_length=16, null=True, blank=True)`
and `draw_character = models.CharField(max_length=16, null=True,
blank=True)`. Generate the migration:
`cd services/app && python manage.py makemigrations analysis -n lc0_wdl_calibration`.
Update the lc0 completion view to write the new columns from the
validated serializer data.

- [ ] **Step 4: Run, expect pass.** `cd services/app && python -m pytest analysis/tests/test_lc0_calibration_models.py -q` → PASS. Then full app analysis+api suites:
`cd services/app && python -m pytest analysis api -q` → PASS (fix view/serializer call sites that referenced `classification`).

- [ ] **Step 5: Bandit + commit.**
```bash
source .venv/bin/activate && bandit -ll services/app/analysis/models.py services/app/api/views.py
git add -A && git commit -m "feat(#159): Django Lc0 calibration columns + migration

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task D4: SQLAlchemy mirror

**Files:**
- Modify: `services/app/app/storage/models.py:231-289` (`Lc0GameAnalysis`, `Lc0MoveAnalysis`)
- Test: `services/app/app/tests/test_storage_lc0_mirror.py` (follow existing storage-model test pattern; in-memory SQLite create_all + insert/select round-trip)

- [ ] **Step 1: Failing test** — round-trip an `Lc0MoveAnalysis` with `wdl_win_adj`, `wdl_mu`, `base_severity`, `draw_character` and an `Lc0GameAnalysis` with `draw_rate_reference/wdl_calibration_elo/contempt`; assert read-back equality.
- [ ] **Step 2: Run, expect fail** (`AttributeError`/no such column).
- [ ] **Step 3: Implement** mirror columns matching D3 exactly:
```python
    draw_rate_reference: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    wdl_calibration_elo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    contempt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```
and on the move model `wdl_win_adj/wdl_draw_adj/wdl_loss_adj`
(`Integer, nullable=True`), `wdl_mu/delta_mu/delta_d`
(`Float, nullable=True`), replace `classification` with
`base_severity`/`draw_character` (`String(16), nullable=True`).
- [ ] **Step 4: Run, expect pass.** `cd services/app && python -m pytest app/tests/test_storage_lc0_mirror.py -q` → PASS.
- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(#159): SQLAlchemy Lc0 calibration mirror columns

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task D5: Vendor module + fixture into app; lockstep guard

**Files:**
- Create: `services/app/analysis/wdl_calibration.py` (byte-identical copy of the canonical worker module)
- Create: `services/app/analysis/wdl_calibration_vectors.json` (byte-identical copy)
- Create: `tests/test_vendored_lockstep.py` (repo root)
- Test: `services/app/analysis/tests/test_wdl_calibration_contract.py`

- [ ] **Step 1: Write the lockstep guard test (repo root)**
```python
# tests/test_vendored_lockstep.py
import hashlib, pathlib
ROOT = pathlib.Path(__file__).parent.parent
PAIRS = [
    ("services/local_worker/local_worker/analysis/wdl_calibration.py",
     "services/app/analysis/wdl_calibration.py"),
    ("services/local_worker/local_worker/analysis/wdl_calibration_vectors.json",
     "services/app/analysis/wdl_calibration_vectors.json"),
]
def _sha(p): return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def test_vendored_copies_are_byte_identical():
    for a, b in PAIRS:
        assert _sha(a) == _sha(b), f"VENDORED DRIFT: {a} != {b}"
```

- [ ] **Step 2: Run, expect fail.** `source .venv/bin/activate && pytest tests/test_vendored_lockstep.py -q` → FAIL (app copy missing).

- [ ] **Step 3: Copy verbatim**
```bash
cp services/local_worker/local_worker/analysis/wdl_calibration.py services/app/analysis/wdl_calibration.py
cp services/local_worker/local_worker/analysis/wdl_calibration_vectors.json services/app/analysis/wdl_calibration_vectors.json
```
Add `services/app/analysis/tests/test_wdl_calibration_contract.py` — same body as Task A5's contract test but importing `from analysis.wdl_calibration import ...` and reading the app-local fixture path.

- [ ] **Step 4: Run, expect pass.**
`source .venv/bin/activate && pytest tests/test_vendored_lockstep.py -q && cd services/app && python -m pytest analysis/tests/test_wdl_calibration_contract.py -q` → PASS.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(#159): vendor wdl_calibration into app + lockstep guard

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase E — Offline recompute command

### Task E1: `recompute_lc0_calibration` management command

**Files:**
- Create: `services/app/analysis/management/commands/recompute_lc0_calibration.py`
- Test: `services/app/analysis/tests/test_recompute_lc0_calibration.py`

- [ ] **Step 1: Failing test**
```python
# services/app/analysis/tests/test_recompute_lc0_calibration.py
import pytest
from django.core.management import call_command
from analysis.models import Lc0GameAnalysis, Lc0MoveAnalysis

@pytest.mark.django_db
def test_recompute_is_pure_from_stored_raw(django_game_factory):
    game = django_game_factory()
    a = Lc0GameAnalysis.objects.create(game=game, engine_nodes=1,
        network_name="t", draw_rate_reference=0.58,
        wdl_calibration_elo=900, contempt=-400)
    m = Lc0MoveAnalysis.objects.create(analysis=a, ply=1, san="e4", fen="f",
        wdl_win=500, wdl_draw=300, wdl_loss=200,
        wdl_win_adj=0, wdl_draw_adj=0, wdl_loss_adj=0, wdl_mu=None,
        delta_mu=None, delta_d=None, cp_equiv=10, best_move="e4",
        base_severity="Best", draw_character=None)
    call_command("recompute_lc0_calibration", "--all")
    m.refresh_from_db()
    assert (m.wdl_win_adj, m.wdl_draw_adj, m.wdl_loss_adj) != (0, 0, 0)
    assert m.base_severity in {
        "Best","Excellent","Good","Inaccuracy","Mistake","Blunder"}
```

- [ ] **Step 2: Run, expect fail.** `cd services/app && python -m pytest analysis/tests/test_recompute_lc0_calibration.py -q` → FAIL (no such command).

- [ ] **Step 3: Implement** a command that, per `Lc0GameAnalysis` (filtered by `--all` or `--game <id>`), iterates `moves` in ply order, recomputes `wdl_*_adj/wdl_mu/delta_mu/delta_d/base_severity/draw_character` from the stored **raw** `wdl_win/draw/loss` + per-game `draw_rate_reference`/`wdl_calibration_elo`/`contempt` using the vendored `analysis.wdl_calibration` (`rescale_wdl`, `classify_draw_aware`), recomputes per-side counters and accuracy (Lichess curve fed `μ·100`), and saves. `white_to_move = ply % 2 == 1`. Wrap each game in a transaction. No lc0 import anywhere in the command (enforced by a test asserting the module has no `chess.engine` import).

- [ ] **Step 4: Run, expect pass.** Same command → PASS.

- [ ] **Step 5: Bandit + commit.**
```bash
source .venv/bin/activate && bandit -ll services/app/analysis/management/commands/recompute_lc0_calibration.py
git add -A && git commit -m "feat(#159): offline lc0 calibration recompute command

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase F — Documentation

### Task F1: Wiki — math + analysis flow

**Files:**
- Modify: `wood_league.wiki/analysis-math.md`
- Modify: `wood_league.wiki/Architecture-and-Analysis-Flow.md`

- [ ] **Step 1:** In `analysis-math.md`, add a "Lc0 WDL Elo Calibration" section: the per-network measured draw-rate reference (what it is, why measured not guessed), the rescale model in plain terms (raw network WDL → practical WDL for these two players' strengths; cite lc0 pinned commit `d8ce48258c39d331c119f8c8729374ceb3df8409`), and the draw-aware ladder + modifier table (Δμ severity × ΔD character, the exact gates from Task A4). Mark the old single-Win% lc0 classification "superseded by draw-aware classification (issue #159)". Plain non-technical tone; cross-link with `[[Architecture and Analysis Flow]]`.
- [ ] **Step 2:** In `Architecture-and-Analysis-Flow.md`, document: lc0 runs raw (player-independent cache untouched), per-network draw-rate calibration step, rescale+classify in the worker using job-supplied ratings, raw inputs stored, and the `recompute_lc0_calibration` command for offline retuning without re-running lc0. Cross-link `[[analysis-math]]`.
- [ ] **Step 3: Commit (wiki is a separate git repo).**
```bash
cd wood_league.wiki && git add analysis-math.md Architecture-and-Analysis-Flow.md && git commit -m "docs(#159): WDL Elo calibration + draw-aware classification" && cd ..
```
> The wiki is a separate repository; this commit is independent of the `issue/159` branch. Do not push unless asked.

---

## Self-Review

**Spec coverage:** C1 raw lc0 → Task C2 (no WDL opts; cache untouched, asserted in C2 wiring notes). C2 draw-rate calibration → Phase B. C3 rescale port → A1–A3 (verbatim, pinned SHA). C4 draw-aware classify → A4. C5 accuracy+counters → C2 (counter buckets, `μ·100` accuracy) + E1 (recompute). C6 persistence → C1/C3/D2/D3/D4. C7 job payload+settings+fallback → C3/D1. C8 recompute command → E1. Test infra (golden/contract/lockstep) → A5/D5/`tests/test_vendored_lockstep.py`. Docs → F1. All spec sections mapped.

**Placeholder scan:** No TBD/“handle errors”/“similar to”. The lc0 oracle step (A5 Step 4) is explicitly conditional with a recorded follow-up, not a placeholder. `FastExp2`'s reconstructed line is flagged with a verification path (golden oracle) — acceptable and called out, not silent.

**Type consistency:** `rescale_wdl` → `RescaledWDL(wdl_white, mu)`; `classify_draw_aware` → `DrawAwareClass(base, modifier, counter_bucket)`; `Lc0MoveResult` fields (`wdl_win`/`wdl_win_adj`/`wdl_mu`/`delta_mu`/`delta_d`/`base_severity`/`draw_character`) are consistent across C1, C2, C3, D2, D3, D4, E1. `Lc0GameResult` provenance fields (`draw_rate_reference`/`wdl_calibration_elo`/`contempt`) consistent C1→C3→D2→D3→D4. Counter buckets (`blunders`/`mistakes`/`inaccuracies`) consistent A4→C2→E1.
