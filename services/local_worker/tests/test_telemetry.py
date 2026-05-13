"""
Title: test_telemetry.py — Unit tests for telemetry module
Description:
    Covers the JSON-backed consent persistence, the interactive prompt
    flow, and the sentry-sdk wiring done by ``init_telemetry``.

Changelog:
    2026-05-12: Initial creation. Issue #43.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_worker import telemetry
from local_worker.telemetry import (
    get_consent,
    init_telemetry,
    prompt_for_consent,
    set_consent,
)


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """Provide an isolated config.json path inside a temp directory."""
    return tmp_path / "config.json"


def test_get_consent_returns_none_when_missing(config_path: Path) -> None:
    """An absent config file must report ``None`` (never asked)."""
    assert get_consent(config_path) is None


def test_set_consent_persists_value(config_path: Path) -> None:
    """``set_consent`` should write both ``telemetry`` and ``asked_at``."""
    set_consent(config_path, True)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["telemetry"] is True
    assert "asked_at" in data
    assert get_consent(config_path) is True


def test_prompt_for_consent_reads_stdin_yes(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``yes`` answer should opt the user in and persist the choice."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert prompt_for_consent(config_path) is True
    # Subsequent call must read from the file, not prompt again.
    monkeypatch.setattr("builtins.input", lambda _prompt="": (_ for _ in ()).throw(
        AssertionError("should not re-prompt")
    ))
    assert prompt_for_consent(config_path) is True


def test_prompt_for_consent_defaults_to_no(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input must persist an explicit ``False``."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert prompt_for_consent(config_path) is False
    assert get_consent(config_path) is False


def test_prompt_for_consent_handles_eof(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed stdin should not crash; treat it as opt-out."""
    def raise_eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert prompt_for_consent(config_path) is False


def test_init_telemetry_skips_when_consent_false() -> None:
    """No DSN lookup, no sentry init, just a clean ``False`` return."""
    assert init_telemetry(consent=False, release="0.3.0") is False


def test_init_telemetry_skips_when_dsn_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consent without a DSN should still no-op gracefully."""
    monkeypatch.setattr(telemetry, "_DEFAULT_GLITCHTIP_DSN", "")
    monkeypatch.delenv("WOOD_LEAGUE_GLITCHTIP_DSN", raising=False)
    assert init_telemetry(consent=True, release="0.3.0") is False


