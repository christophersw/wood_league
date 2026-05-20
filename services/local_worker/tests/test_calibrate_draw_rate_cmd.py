"""
Title: test_calibrate_draw_rate_cmd.py — Tests for `wlworker calibrate-draw-rate`
Description:
    Phase A of issue #161. The CLI is a thin wrapper that (1) launches lc0,
    (2) runs the existing draw-rate sampler, (3) POSTs the result to the
    app's NetworkCalibration endpoint. These tests inject fakes for the
    engine launcher, sampler, and worker-client submitter so no real lc0
    process or network call is involved.

Changelog:
    2026-05-19 (#161/A): Initial.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from typer.testing import CliRunner

from local_worker.cli import app


@dataclass
class _FakeDrawRateResult:
    """Stand-in for analysis.lc0_draw_rate.DrawRateResult."""
    network: str
    draw_rate_reference: float
    n_samples: int
    stderr: float


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict:
    """Provide minimal config + capture handles for the CLI to run end-to-end.

    Returns a dict the test asserts against. Sets WLW_LOG_DIR so the global
    --log-level/log-file machinery does not write into the user's home dir.
    """
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    captured: dict[str, Any] = {}

    def fake_launch_engine(*_args: Any, **_kwargs: Any):
        class _Engine:
            def quit(self) -> None:
                captured["engine_quit"] = True
        return _Engine()

    def fake_measure_draw_rate(
        engine: Any,
        *,
        network: str,
        sem_target: float,
        max_samples: int,
        nodes: int,
    ) -> _FakeDrawRateResult:
        captured["sampler_call"] = {
            "network": network,
            "sem_target": sem_target,
            "max_samples": max_samples,
            "nodes": nodes,
        }
        return _FakeDrawRateResult(
            network=network, draw_rate_reference=0.612, n_samples=42, stderr=0.0041,
        )

    class _FakeClient:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            captured["client_init"] = {"base_url": base_url, "api_key": api_key}

        def submit_network_calibration(self, **kwargs: Any) -> dict:
            captured["submit"] = kwargs
            return {"created": True}

    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.launch_lc0_engine",
        fake_launch_engine,
    )
    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.measure_draw_rate",
        fake_measure_draw_rate,
    )
    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.WorkerClient",
        _FakeClient,
    )
    return captured


_HAPPY_ARGS = [
    "calibrate-draw-rate",
    "--network", "BT4-1740",
    "--sem-target", "0.005",
    "--nodes", "800",
    "--max-positions", "10000",
    "--sampler-version", "v1",
    "--settings-hash", "a" * 64,
    "--api-base", "https://app.test",
    "--api-key", "k",
    "--worker-id", "w-1",
]


def test_calibrate_draw_rate_invokes_sampler_with_expected_settings(cli_env: dict) -> None:
    """The sampler is called with values forwarded from CLI flags."""
    result = CliRunner().invoke(app, _HAPPY_ARGS)
    assert result.exit_code == 0, result.output
    assert cli_env["sampler_call"] == {
        "network": "BT4-1740",
        "sem_target": 0.005,
        "max_samples": 10000,
        "nodes": 800,
    }
    assert cli_env.get("engine_quit") is True


def test_calibrate_draw_rate_submits_measurement_to_app(cli_env: dict) -> None:
    """The submit payload mirrors the measurement plus CLI-provided identity."""
    result = CliRunner().invoke(app, _HAPPY_ARGS)
    assert result.exit_code == 0, result.output
    assert cli_env["client_init"] == {"base_url": "https://app.test", "api_key": "k"}
    assert cli_env["submit"] == {
        "network_name": "BT4-1740",
        "settings_hash": "a" * 64,
        "draw_rate_reference": 0.612,
        "sample_size": 42,
        "sem": 0.0041,
        "sampler_version": "v1",
        "worker_id": "w-1",
    }


def test_calibrate_draw_rate_reports_idempotent_no_op(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When the app returns created=False, the CLI exits 0 and surfaces the no-op."""
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))

    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.launch_lc0_engine",
        lambda *a, **kw: type("E", (), {"quit": lambda self: None})(),
    )
    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.measure_draw_rate",
        lambda engine, **kw: _FakeDrawRateResult(kw["network"], 0.5, 10, 0.01),
    )

    class _FakeClient:
        def __init__(self, **kw: Any) -> None: ...

        def submit_network_calibration(self, **kw: Any) -> dict:
            return {"created": False}

    monkeypatch.setattr(
        "local_worker.commands.calibrate_draw_rate_cmd.WorkerClient", _FakeClient
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "calibrate-draw-rate",
            "--network", "n",
            "--sem-target", "0.005",
            "--nodes", "800",
            "--max-positions", "1000",
            "--sampler-version", "v1",
            "--settings-hash", "b" * 64,
            "--api-base", "https://app.test",
            "--api-key", "k",
            "--worker-id", "w",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "already calibrated" in result.output.lower() or "no-op" in result.output.lower()
