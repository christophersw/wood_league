"""
Title: test_baked_lc0_tuning.py — Structural guard for the baked L40S calibration
Description:
    vast/lc0_tuning.l40s.json is COPYd into the image at the data-dir
    path (/data/wlw/lc0_tuning.json) so a fresh instance is a
    calibration cache hit and skips the ~7.5-min lc0 MinibatchSize
    sweep. This guards the committed artifact's shape — a malformed or
    empty bake silently degrades to a full sweep, which is exactly the
    cost we are removing (issue #150, plan Task 6 / Phase 1). Captured
    from a real L40S sea-trial (worker 0.9.15, BT4 / onnx-trt) on
    2026-05-18.
Changelog:
    2026-05-18: Initial creation (issue #150, Phase 1).
"""
import json
from pathlib import Path

_BAKED = (
    Path(__file__).resolve().parent.parent / "vast" / "lc0_tuning.l40s.json"
)


def test_baked_calibration_is_well_formed():
    """The committed bake matches the on-disk lc0_tuning.json schema.

    Mirrors the fields lc0_tuning.get_tuned_opts() reads on a cache
    hit; a mismatch here means a fresh instance would miss and pay
    the full calibration sweep.

    Returns:
        None: assertion failure if the artifact is malformed.
    """
    data = json.loads(_BAKED.read_text())
    fp = data["fingerprint"]
    assert set(fp) == {"gpu", "lc0_version", "weights", "backend"}
    assert fp["weights"] == "BT4.pb.gz"  # matches image WLW_LC0_WEIGHTS_PATH
    assert fp["backend"]  # non-empty backend
    assert isinstance(data["minibatch_size"], int) and data["minibatch_size"] >= 1
    assert isinstance(data["max_prefetch"], int) and data["max_prefetch"] >= 0
    assert float(data["measured_nps"]) > 0
