# Title: test_wdl_calibration_contract.py
# Description: Cross-service golden-vector contract test for wdl_calibration.
#   Asserts that rescale_wdl and classify_draw_aware produce byte-identical
#   results to the frozen fixture in wdl_calibration_vectors.json.  The
#   companion Task D5 vendors that same JSON into the Django app and runs an
#   identical assertion there, providing a two-repo regression guard.
# Changelog:
#   2026-05-19 — Initial implementation for issue #159 Task A5.

import json
import pathlib

from local_worker.analysis.wdl_calibration import rescale_wdl, classify_draw_aware

FIX = (
    pathlib.Path(__file__).parents[1]
    / "local_worker"
    / "analysis"
    / "wdl_calibration_vectors.json"
)


def test_contract_vectors_match():
    """Assert that live outputs match the frozen golden-vector fixture.

    Reads wdl_calibration_vectors.json and replays every rescale and classify
    case against the current implementation.  Any divergence indicates a
    breaking change to the cross-service contract.

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
