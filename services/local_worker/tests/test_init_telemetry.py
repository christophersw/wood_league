"""
Title: test_init_telemetry.py — sentry_sdk wiring tests
Description:
    Covers ``init_telemetry``'s sentry_sdk.init kwargs, tag setting, and
    LoggingIntegration threshold wiring. Split out from
    ``test_telemetry.py`` to keep each test module's Halstead effort
    under the project's quality bar.

Changelog:
    2026-05-13: Extracted from test_telemetry.py (issue #50).
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from local_worker.telemetry import init_telemetry


def _install_sentry_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Stub out sentry_sdk.init / set_tag and return capture dicts."""
    captured: dict[str, Any] = {}
    tags: dict[str, str] = {}

    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: captured.update(kw))
    monkeypatch.setattr(
        sentry_sdk, "set_tag", lambda name, value: tags.__setitem__(name, value)
    )
    return captured, tags


def test_init_telemetry_initialises_when_consent_and_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sentry_sdk.init must be called with the resolved DSN and release."""
    captured, tags = _install_sentry_capture(monkeypatch)
    monkeypatch.setenv("WOOD_LEAGUE_GLITCHTIP_DSN", "https://example@glitchtip/1")
    result = init_telemetry(
        consent=True,
        release="0.4.3",
        environment_info={
            "host": {"system": "Darwin", "machine": "arm64"},
            "python": {"version": "3.12.4"},
            "engines": {"stockfish": {"path": "/usr/bin/stockfish"}},
        },
        worker_id="install-token-abc",
    )
    assert result is True
    assert captured["dsn"] == "https://example@glitchtip/1"
    assert captured["release"] == "0.4.3"
    assert tags["os"] == "Darwin"
    assert tags["engines"] == "stockfish"
    assert tags["worker_id"] != "install-token-abc"


def test_init_telemetry_enables_structured_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_telemetry must pass _experiments enable_logs to sentry_sdk.init."""
    captured, _ = _install_sentry_capture(monkeypatch)
    monkeypatch.setenv("WOOD_LEAGUE_GLITCHTIP_DSN", "https://example@glitchtip/1")
    init_telemetry(consent=True, release="0.4.3")
    assert captured.get("_experiments") == {"enable_logs": True}


def test_init_telemetry_uses_log_level_for_integration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """log_level must flow into LoggingIntegration's breadcrumb threshold."""
    captured, _ = _install_sentry_capture(monkeypatch)
    monkeypatch.setenv("WOOD_LEAGUE_GLITCHTIP_DSN", "https://example@glitchtip/1")
    init_telemetry(consent=True, release="0.4.3", log_level="DEBUG")
    integration = (captured.get("integrations") or [None])[0]
    assert integration._breadcrumb_handler.level == logging.DEBUG
