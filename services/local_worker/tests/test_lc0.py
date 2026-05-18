"""
Title: test_lc0.py — lc0 analysis module wiring tests
Description:
    Tests for lc0.py wiring/integration points — currently that
    _merge_tuned_opts hands get_tuned_opts the push_after_calibrate
    hook so a fresh calibration is persisted to object storage.
Changelog:
    2026-05-17: Initial creation — on_calibrated push wiring (#150).
"""


def test_merge_tuned_opts_passes_push_hook(monkeypatch):
    """_merge_tuned_opts must hand get_tuned_opts the push_after_calibrate
    hook so a fresh calibration is persisted to the bucket."""
    from local_worker.analysis import lc0

    seen = {}

    def fake_get_tuned_opts(**kwargs):
        seen["on_calibrated"] = kwargs.get("on_calibrated")
        return {}

    monkeypatch.setattr(lc0, "get_tuned_opts", fake_get_tuned_opts)

    lc0._merge_tuned_opts(
        {}, lc0_path="/opt/lc0/lc0", weights_path="/opt/weights/BT4.pb.gz",
        backend="onnx-trt",
    )

    from local_worker.lc0_tuning_sync import push_after_calibrate
    assert seen["on_calibrated"] is push_after_calibrate
