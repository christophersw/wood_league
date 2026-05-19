"""
Title: test_lc0.py — lc0 analysis module wiring tests
Description:
    Tests for lc0.py wiring/integration points — currently that
    _merge_tuned_opts hands get_tuned_opts the push_after_calibrate
    hook so a fresh calibration is persisted to object storage, and
    four integration paths for _get_or_measure_draw_rate (issue #159 B1).
Changelog:
    2026-05-17: Initial creation — on_calibrated push wiring (#150).
    2026-05-19: Add _get_or_measure_draw_rate integration tests (#159 B1).
"""
import pytest

from local_worker.analysis.lc0_draw_rate import DrawRateResult


# ---------------------------------------------------------------------------
# Fixture: reset the module-level _draw_rate_cache between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def clear_draw_rate_cache():
    """Clear _draw_rate_cache before and after each test that uses it."""
    from local_worker.analysis import lc0
    lc0._draw_rate_cache.clear()
    yield
    lc0._draw_rate_cache.clear()


# ---------------------------------------------------------------------------
# _get_or_measure_draw_rate — four paths
# ---------------------------------------------------------------------------

def test_get_or_measure_draw_rate_in_process_cache_hit(monkeypatch, clear_draw_rate_cache):
    """Path (a): in-process cache hit returns cached value without measuring."""
    from local_worker.analysis import lc0

    cached_result = DrawRateResult(
        network="BT4", draw_rate_reference=0.42, n_samples=10, stderr=0.001
    )
    lc0._draw_rate_cache["BT4"] = cached_result

    measure_calls = []
    pull_calls = []

    monkeypatch.setattr(lc0, "measure_draw_rate", lambda *a, **k: measure_calls.append(1) or cached_result)
    monkeypatch.setattr(lc0, "pull_draw_rate", lambda *a, **k: pull_calls.append(1) or None)

    result = lc0._get_or_measure_draw_rate(object(), "BT4")  # type: ignore[arg-type]

    assert result == pytest.approx(0.42)
    assert measure_calls == [], "measure_draw_rate must NOT be called on a cache hit"
    assert pull_calls == [], "pull_draw_rate must NOT be called on a cache hit"


def test_get_or_measure_draw_rate_disk_hit_populates_in_process_cache(
    monkeypatch, clear_draw_rate_cache
):
    """Path (b): disk hit populates in-process cache and returns persisted value."""
    from local_worker.analysis import lc0

    measure_calls = []

    monkeypatch.setattr(lc0, "pull_draw_rate", lambda network, path: 0.38)
    monkeypatch.setattr(lc0, "measure_draw_rate", lambda *a, **k: measure_calls.append(1))

    result = lc0._get_or_measure_draw_rate(object(), "BT4")  # type: ignore[arg-type]

    assert result == pytest.approx(0.38)
    assert measure_calls == [], "measure_draw_rate must NOT be called on a disk hit"
    # In-process cache must now hold the value
    assert "BT4" in lc0._draw_rate_cache
    assert lc0._draw_rate_cache["BT4"].draw_rate_reference == pytest.approx(0.38)


def test_get_or_measure_draw_rate_no_cache_measures_and_persists(
    monkeypatch, clear_draw_rate_cache
):
    """Path (c): no cache + no disk → measures, persists, and populates in-process cache."""
    from local_worker.analysis import lc0

    measured = DrawRateResult(network="BT4", draw_rate_reference=0.45, n_samples=8, stderr=0.003)
    push_calls: list[tuple] = []

    monkeypatch.setattr(lc0, "pull_draw_rate", lambda network, path: None)
    monkeypatch.setattr(lc0, "measure_draw_rate", lambda engine, network, **kw: measured)
    monkeypatch.setattr(
        lc0, "push_draw_rate",
        lambda network, draw_rate, path: push_calls.append((network, draw_rate))
    )

    result = lc0._get_or_measure_draw_rate(object(), "BT4")  # type: ignore[arg-type]

    assert result == pytest.approx(0.45)
    # push must have been called with the right args
    assert len(push_calls) == 1
    assert push_calls[0][0] == "BT4"
    assert push_calls[0][1] == pytest.approx(0.45)
    # in-process cache must be populated
    assert "BT4" in lc0._draw_rate_cache
    assert lc0._draw_rate_cache["BT4"].draw_rate_reference == pytest.approx(0.45)


def test_get_or_measure_draw_rate_measurement_failure_returns_fallback(
    monkeypatch, clear_draw_rate_cache
):
    """Path (d): measure_draw_rate raising → returns 0.5 fallback without propagating."""
    from local_worker.analysis import lc0

    monkeypatch.setattr(lc0, "pull_draw_rate", lambda network, path: None)
    monkeypatch.setattr(lc0, "measure_draw_rate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("lc0 crashed")))

    result = lc0._get_or_measure_draw_rate(object(), "BT4")  # type: ignore[arg-type]

    assert result == pytest.approx(0.5)


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
