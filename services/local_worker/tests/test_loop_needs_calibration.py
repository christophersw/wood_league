"""
Title: test_loop_needs_calibration.py — Run-loop 409 NEEDS_CALIBRATION handler
Description:
    Issue #161 Phase B. When the app responds 409 NEEDS_CALIBRATION on
    checkout, the loop's helper runs the existing draw-rate sampler with the
    settings carried in the error, POSTs the result via
    ``submit_network_calibration``, and returns so the caller can retry.

Changelog:
    2026-05-19 (#161/B): Initial.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from local_worker import loop as worker_loop
from local_worker.worker_client import NeedsCalibrationError


@dataclass
class _Result:
    """Stand-in for analysis.lc0_draw_rate.DrawRateResult."""
    network: str
    draw_rate_reference: float
    n_samples: int
    stderr: float


class _RecordingClient:
    """Captures submit_network_calibration calls without doing IO."""

    def __init__(self) -> None:
        self.submissions: list[dict] = []

    def submit_network_calibration(self, **kwargs: Any) -> dict:
        """Record the kwargs and return a created=True response."""
        self.submissions.append(kwargs)
        return {"created": True}


def _make_err() -> NeedsCalibrationError:
    """Build a representative NeedsCalibrationError payload from the app."""
    return NeedsCalibrationError(
        network_name="BT4-1740",
        settings_hash="a" * 64,
        sampler_settings={
            "sem_target": 0.005,
            "nodes": 800,
            "max_positions": 10000,
            "sampler_version": "v1",
        },
        sampler_version="v1",
    )


def test_handle_needs_calibration_runs_sampler_with_supplied_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sampler is called with the exact settings from the 409 body."""
    captured: dict = {}

    def fake_measure_draw_rate(
        engine: Any, *, network: str, sem_target: float,
        max_samples: int, nodes: int,
    ) -> _Result:
        captured["call"] = dict(
            network=network, sem_target=sem_target,
            max_samples=max_samples, nodes=nodes,
        )
        return _Result(network, 0.612, 42, 0.0041)

    monkeypatch.setattr(worker_loop, "measure_draw_rate", fake_measure_draw_rate)

    engine = SimpleNamespace()  # opaque to the helper
    client = _RecordingClient()
    worker_loop.handle_needs_calibration(
        engine=engine, error=_make_err(), client=client, worker_id="w-1",
    )
    assert captured["call"] == {
        "network": "BT4-1740",
        "sem_target": 0.005,
        "max_samples": 10000,
        "nodes": 800,
    }


def test_handle_needs_calibration_submits_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sampler result is POSTed with the settings_hash from the error."""
    monkeypatch.setattr(
        worker_loop, "measure_draw_rate",
        lambda engine, **kw: _Result(kw["network"], 0.612, 42, 0.0041),
    )
    client = _RecordingClient()
    worker_loop.handle_needs_calibration(
        engine=SimpleNamespace(), error=_make_err(),
        client=client, worker_id="w-1",
    )
    assert client.submissions == [{
        "network_name": "BT4-1740",
        "settings_hash": "a" * 64,
        "draw_rate_reference": 0.612,
        "sample_size": 42,
        "sem": 0.0041,
        "sampler_version": "v1",
        "worker_id": "w-1",
    }]
