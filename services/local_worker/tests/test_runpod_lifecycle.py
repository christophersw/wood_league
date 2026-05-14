"""
Title: test_runpod_lifecycle.py — Tests for the RunPod self-stop helper
Description:
    Verifies that ``stop_self`` posts to the right URL with the right
    Authorization header, returns True on 2xx and False on errors without
    raising, and that ``resolve_pod_id`` prefers the explicit settings
    value over the ``RUNPOD_POD_ID`` environment variable.

Changelog:
    2026-05-14: Initial creation for issue #81.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from local_worker.config import Settings
from local_worker.runpod_lifecycle import resolve_pod_id, stop_self


class _FakeResponse:
    """Minimal stand-in for ``httpx.Response`` used by these tests."""

    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


@pytest.fixture(autouse=True)
def _clear_runpod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip any ambient ``RUNPOD_POD_ID`` so the host shell can't pollute tests."""
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)


def test_stop_self_returns_true_on_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 response from RunPod must yield True and use a Bearer header."""
    captured: dict[str, Any] = {}

    def fake_post(url: str, headers: dict[str, str], timeout: float) -> _FakeResponse:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _FakeResponse(200, "{}")

    monkeypatch.setattr(httpx, "post", fake_post)

    ok = stop_self("pod-abc", "secret-key", timeout=4.5)

    assert ok is True
    assert captured["url"] == "https://rest.runpod.io/v1/pods/pod-abc/stop"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["timeout"] == 4.5


def test_stop_self_returns_false_on_401(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 401 response must return False and log a WARNING."""
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *_a, **_kw: _FakeResponse(401, "unauthorized"),
    )

    with caplog.at_level(logging.WARNING, logger="local_worker.runpod_lifecycle"):
        ok = stop_self("pod-abc", "bad-key")

    assert ok is False
    assert any("failed" in record.message and "401" in record.message for record in caplog.records)


def test_stop_self_swallows_network_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A network error must return False, log WARNING, and not raise."""

    def boom(*_a: Any, **_kw: Any) -> _FakeResponse:
        raise httpx.ConnectError("nope")

    monkeypatch.setattr(httpx, "post", boom)

    with caplog.at_level(logging.WARNING, logger="local_worker.runpod_lifecycle"):
        ok = stop_self("pod-abc", "secret-key")

    assert ok is False
    assert any("network error" in record.message for record in caplog.records)


def test_stop_self_truncates_response_body_in_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Huge error bodies must not flood the log; they are capped at 500 chars."""
    big_body = "x" * 5000
    monkeypatch.setattr(httpx, "post", lambda *_a, **_kw: _FakeResponse(500, big_body))

    with caplog.at_level(logging.WARNING, logger="local_worker.runpod_lifecycle"):
        stop_self("pod-abc", "secret-key")

    failure_logs = [record for record in caplog.records if "failed" in record.message]
    assert failure_logs, "expected a failure log line"
    assert "x" * 501 not in failure_logs[0].message


def test_resolve_pod_id_prefers_explicit_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit settings value must win over the injected env var."""
    monkeypatch.setenv("RUNPOD_POD_ID", "from-env")
    settings = Settings(runpod_pod_id="from-settings")
    assert resolve_pod_id(settings) == "from-settings"


def test_resolve_pod_id_falls_back_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an explicit value, the ``RUNPOD_POD_ID`` env var is used."""
    monkeypatch.setenv("RUNPOD_POD_ID", "from-env")
    settings = Settings()
    assert resolve_pod_id(settings) == "from-env"


def test_resolve_pod_id_returns_none_when_unset() -> None:
    """With nothing configured, ``resolve_pod_id`` must return None."""
    settings = Settings()
    assert resolve_pod_id(settings) is None


def test_resolve_pod_id_ignores_blank_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace-only settings/env values must be treated as missing."""
    monkeypatch.setenv("RUNPOD_POD_ID", "   ")
    settings = Settings(runpod_pod_id="   ")
    assert resolve_pod_id(settings) is None
