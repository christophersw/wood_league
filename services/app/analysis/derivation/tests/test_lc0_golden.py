"""
Title: test_lc0_golden.py — Frozen Lc0 calibration / classify contract
Description:
    Issue #161 Phase D. ``derivation/golden_vectors/lc0.json`` pins the
    expected outputs of ``rescale_wdl`` and ``classify_draw_aware`` for a
    representative cross-section of (Elo, draw-rate, mover, raw-WDL) inputs.
    The math port is the contract — golden vectors fail loudly the moment the
    float32 discipline, the lc0 commit pin, or the band ladder drift.

    This is the app-side successor to
    ``analysis/tests/test_wdl_calibration_contract.py`` (D5 vendored copy);
    that file disappears in Phase I along with the worker mirror.

Changelog:
    2026-05-19 (#161/D): Initial.
"""
from __future__ import annotations

import json
import pathlib

from analysis.derivation.lc0 import classify_draw_aware, rescale_wdl

_FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "golden_vectors" / "lc0.json"
)


def test_rescale_wdl_matches_golden_vectors() -> None:
    """Every rescale row in the fixture matches the ported math byte-for-byte."""
    data = json.loads(_FIXTURE.read_text())
    for case in data["rescale"]:
        result = rescale_wdl(**case["in"])
        assert list(result.wdl_white) == case["out"]["wdl_white"], case["name"]
        assert abs(result.mu - case["out"]["mu"]) <= 1e-4, case["name"]


def test_classify_draw_aware_matches_golden_vectors() -> None:
    """Every classify row in the fixture maps to (base, modifier) verbatim."""
    data = json.loads(_FIXTURE.read_text())
    for case in data["classify"]:
        out = classify_draw_aware(case["in"]["delta_mu"], case["in"]["delta_d"])
        assert [out.base, out.modifier] == case["out"], case["name"]


def test_lc0_pinned_sha_recorded() -> None:
    """The golden vectors record the lc0 commit they were generated against."""
    data = json.loads(_FIXTURE.read_text())
    assert isinstance(data.get("_lc0_pinned_sha"), str)
    assert len(data["_lc0_pinned_sha"]) >= 7
