"""
Title: test_telemetry_bridge.py — Structured-logs bridge unit tests
Description:
    Covers the stdlib-to-sentry-logger bridge installed by
    ``init_telemetry``. Split out from ``test_telemetry.py`` to keep
    each test module's Halstead effort under the project's quality bar.

Changelog:
    2026-05-13: Extracted from test_telemetry.py (issue #48).
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from local_worker import telemetry
from local_worker.telemetry import init_telemetry


def _clear_bridges() -> None:
    """Remove any installed bridge handlers from the root logger."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, telemetry._SentryLogsBridge):
            root.removeHandler(handler)


def _find_bridge() -> telemetry._SentryLogsBridge | None:
    """Return the first installed bridge handler, or ``None``."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, telemetry._SentryLogsBridge):
            return handler
    return None


def _make_record(level: int, message: str) -> logging.LogRecord:
    """Build a minimal stdlib log record for bridge tests."""
    return logging.LogRecord(
        name="t", level=level, pathname=__file__, lineno=1,
        msg=message, args=(), exc_info=None,
    )


@pytest.mark.parametrize(
    "level, expected",
    [(20, "info"), (30, "warning"), (40, "error"), (50, "fatal")],
)
def test_bridge_forwards_to_sentry_logger(
    monkeypatch: pytest.MonkeyPatch, level: int, expected: str,
) -> None:
    """The bridge must call sentry_sdk.logger.<level> per record."""
    import sentry_sdk

    seen: list[tuple[str, str]] = []

    class _FakeLogger:
        def __getattr__(self, name: str) -> Any:
            return lambda msg, **_: seen.append((name, msg))

    monkeypatch.setattr(sentry_sdk, "logger", _FakeLogger(), raising=False)
    telemetry._SentryLogsBridge().emit(_make_record(level, "m"))
    assert seen == [(expected, "m")]


def test_bridge_install_is_idempotent() -> None:
    """Re-running install must not attach duplicate handlers."""
    _clear_bridges()
    try:
        telemetry._install_structured_logs_bridge()
        telemetry._install_structured_logs_bridge()
        assert (
            sum(
                1
                for handler in logging.getLogger().handlers
                if isinstance(handler, telemetry._SentryLogsBridge)
            )
            == 1
        )
    finally:
        _clear_bridges()


def test_bridge_install_updates_level_in_place() -> None:
    """A second install with a new level must re-tune the existing bridge."""
    _clear_bridges()
    try:
        telemetry._install_structured_logs_bridge(level=logging.WARNING)
        telemetry._install_structured_logs_bridge(level=logging.DEBUG)
        bridge = _find_bridge()
        assert bridge is not None and bridge.level == logging.DEBUG
    finally:
        _clear_bridges()


def test_init_telemetry_passes_log_level_to_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """init_telemetry must propagate log_level to the bridge handler."""
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **_: None)
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a, **kw: None)
    monkeypatch.setenv("WOOD_LEAGUE_GLITCHTIP_DSN", "https://example@glitchtip/1")
    _clear_bridges()
    try:
        init_telemetry(consent=True, release="0.4.2", log_level="DEBUG")
        bridge = _find_bridge()
        assert bridge is not None and bridge.level == logging.DEBUG
    finally:
        _clear_bridges()
