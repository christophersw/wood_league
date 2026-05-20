# Title: test_wdl_calibration_contract.py
# Description: App-side golden-vector contract test for the vendored
#   wdl_calibration module.  Mirrors the worker contract test at
#   services/local_worker/tests/test_wdl_calibration_contract.py and asserts
#   that the vendored copy produces byte-identical results to the frozen
#   fixture in wdl_calibration_vectors.json.
# Changelog:
#   2026-05-19 — Initial implementation for issue #159 Task D5.

import json
import pathlib

from analysis.wdl_calibration import classify_draw_aware, rescale_wdl

FIX = pathlib.Path(__file__).parent.parent / "wdl_calibration_vectors.json"


def test_contract_vectors_match():
    """Assert that the vendored app module matches the frozen golden-vector fixture.

    Reads wdl_calibration_vectors.json (app-local copy) and replays every
    rescale and classify case against the vendored implementation.  Any
    divergence indicates either accidental in-repo edits to the vendored copy
    or a module-resolution issue with the app-side import path.

    Parameters: none (fixture path is module-level constant FIX).
    Returns: None (pytest assertion).
    Side effects: none.
    """
    data = json.loads(FIX.read_text())
    for case in data["rescale"]:
        out = rescale_wdl(**case["in"])
        assert list(out.wdl_white) == case["out"]["wdl_white"], case["name"]
        assert abs(out.mu - case["out"]["mu"]) <= 1e-4, case["name"]
    for case in data["classify"]:
        c = classify_draw_aware(case["in"]["delta_mu"], case["in"]["delta_d"])
        assert [c.base, c.modifier] == case["out"], case["name"]
