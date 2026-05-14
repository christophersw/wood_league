"""
Title: test_session_end_upload.py — Tests for the graceful-exit log uploader
Description:
    Verifies that the ``commands.run._maybe_upload_log`` helper added in
    issue #85 only fires when the worker is configured and consent is
    granted, that it forwards the new ``session_end`` reason to
    ``upload_log``, and that any exception from the uploader is
    swallowed so the surrounding ``finally`` chain stays intact.

Changelog:
    2026-05-14: Initial creation for issue #85.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

from local_worker._log_upload_meta import SESSION_END
from local_worker.commands import run as run_cmd
from local_worker.config import Settings


def _settings(**overrides: Any) -> Settings:
    """Build a configured ``Settings`` instance for the upload hook tests."""
    base = dict(
        api_url="https://example.com",
        api_key="secret-token",
    )
    base.update(overrides)
    return Settings(**base)


def test_maybe_upload_log_noop_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``upload_log`` must not be called when the worker has no API config."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_cmd, "upload_log", lambda **kw: calls.append(kw) or 1,
    )
    monkeypatch.setattr(run_cmd, "get_consent", lambda: True)

    run_cmd._maybe_upload_log(Settings(api_url="", api_key=""))

    assert calls == []


def test_maybe_upload_log_noop_when_consent_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``upload_log`` must not be called when consent is not granted."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_cmd, "upload_log", lambda **kw: calls.append(kw) or 1,
    )
    monkeypatch.setattr(run_cmd, "get_consent", lambda: False)

    run_cmd._maybe_upload_log(_settings())

    assert calls == []


def test_maybe_upload_log_calls_upload_once_with_session_end_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consent granted → exactly one upload_log call with the SESSION_END reason."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_cmd, "upload_log", lambda **kw: calls.append(kw) or 7,
    )
    monkeypatch.setattr(run_cmd, "get_consent", lambda: True)

    run_cmd._maybe_upload_log(_settings())

    assert len(calls) == 1
    assert calls[0] == {"reason": SESSION_END}


def test_maybe_upload_log_swallows_upload_exceptions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising ``upload_log`` must be caught and logged at WARNING."""

    def fake_upload(**_kwargs: Any) -> int:
        raise RuntimeError("boom")

    monkeypatch.setattr(run_cmd, "upload_log", fake_upload)
    monkeypatch.setattr(run_cmd, "get_consent", lambda: True)

    with caplog.at_level(logging.WARNING, logger="local_worker.commands.run"):
        # Must not raise — the surrounding ``finally`` block would lose
        # the RunPod self-stop call otherwise.
        run_cmd._maybe_upload_log(_settings())

    assert any("session_end log upload raised" in r.message for r in caplog.records)
