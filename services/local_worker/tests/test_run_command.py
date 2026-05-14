"""
Title: test_run_command.py — Tests for the ``run`` command's self-stop hook
Description:
    Verifies the post-drain RunPod self-stop hook fires only when enabled,
    that it resolves the pod id from settings or env, and that a missing
    pod id logs a warning instead of making an HTTP call.

Changelog:
    2026-05-14: Initial creation for issue #81.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from local_worker.commands import run as run_cmd
from local_worker.config import Settings


def _settings(**overrides: Any) -> Settings:
    """Build a ``Settings`` instance with self-stop-relevant defaults filled in."""
    base = dict(
        runpod_self_stop_enabled=False,
        runpod_api_key="",
        runpod_pod_id="",
    )
    base.update(overrides)
    return Settings(**base)


def test_maybe_stop_runpod_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag off, ``stop_self`` must not be called."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        lambda pod_id, api_key: calls.append((pod_id, api_key)) or True,
    )

    run_cmd._maybe_stop_runpod(
        _settings(runpod_self_stop_enabled=False, runpod_api_key="k", runpod_pod_id="p")
    )

    assert calls == []


def test_maybe_stop_runpod_calls_stop_with_resolved_pod_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled + creds present → exactly one ``stop_self`` call with the pod id."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        lambda pod_id, api_key: calls.append((pod_id, api_key)) or True,
    )

    run_cmd._maybe_stop_runpod(
        _settings(
            runpod_self_stop_enabled=True,
            runpod_api_key="api-key-1",
            runpod_pod_id="pod-xyz",
        )
    )

    assert calls == [("pod-xyz", "api-key-1")]


def test_maybe_stop_runpod_resolves_pod_id_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no explicit pod id is set, the ``RUNPOD_POD_ID`` env var is used."""
    monkeypatch.setenv("RUNPOD_POD_ID", "pod-from-env")
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        lambda pod_id, api_key: calls.append((pod_id, api_key)) or True,
    )

    run_cmd._maybe_stop_runpod(
        _settings(runpod_self_stop_enabled=True, runpod_api_key="api-key-1")
    )

    assert calls == [("pod-from-env", "api-key-1")]


def test_maybe_stop_runpod_warns_when_pod_id_unresolvable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Flag on + creds present but no pod id → log WARNING, no HTTP call."""
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    called = False

    def fake_stop(*_a: Any, **_kw: Any) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(run_cmd, "stop_self", fake_stop)

    with caplog.at_level(logging.WARNING, logger="local_worker.commands.run"):
        run_cmd._maybe_stop_runpod(
            _settings(runpod_self_stop_enabled=True, runpod_api_key="api-key-1")
        )

    assert called is False
    assert any("no pod id resolvable" in record.message for record in caplog.records)


def test_maybe_stop_runpod_warns_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Flag on but no api key → log WARNING, no HTTP call."""
    called = False

    def fake_stop(*_a: Any, **_kw: Any) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(run_cmd, "stop_self", fake_stop)

    with caplog.at_level(logging.WARNING, logger="local_worker.commands.run"):
        run_cmd._maybe_stop_runpod(
            _settings(runpod_self_stop_enabled=True, runpod_pod_id="pod-xyz")
        )

    assert called is False
    assert any("WLW_RUNPOD_API_KEY" in record.message for record in caplog.records)
