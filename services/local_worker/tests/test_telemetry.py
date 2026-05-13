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
from typing import Any

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


def _install_sentry_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Stub out ``sentry_sdk.init`` / ``set_tag`` and return capture dicts.

    Args:
        monkeypatch: Pytest fixture used to patch the global ``sentry_sdk``
            module for the duration of the calling test.

    Returns:
        Tuple ``(captured_init_kwargs, captured_tags)`` whose contents are
        populated by the stubbed sentry callables when ``init_telemetry``
        is invoked.
    """
    captured: dict[str, Any] = {}
    tags: dict[str, str] = {}

    import sentry_sdk

    def fake_init(**kwargs: Any) -> None:
        captured.update(kwargs)

    def fake_set_tag(name: str, value: str) -> None:
        tags[name] = value

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    monkeypatch.setattr(sentry_sdk, "set_tag", fake_set_tag)
    return captured, tags


def test_init_telemetry_initialises_when_consent_and_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sentry_sdk.init must be called with the resolved DSN and release."""
    captured, tags = _install_sentry_capture(monkeypatch)
    monkeypatch.setenv("WOOD_LEAGUE_GLITCHTIP_DSN", "https://example@glitchtip/1")

    result = init_telemetry(
        consent=True,
        release="0.3.0",
        environment_info={
            "host": {"system": "Darwin", "machine": "arm64"},
            "python": {"version": "3.12.4"},
            "engines": {"stockfish": {"path": "/usr/bin/stockfish"}, "lc0": {"path": None}},
        },
        worker_id="install-token-abc",
    )

    assert result is True
    expected_init = {
        "dsn": "https://example@glitchtip/1",
        "release": "0.3.0",
    }
    for key, value in expected_init.items():
        assert captured[key] == value
    assert "integrations" in captured

    expected_tags = {
        "os": "Darwin",
        "arch": "arm64",
        "python": "3.12.4",
        "engines": "stockfish",
    }
    assert {k: tags[k] for k in expected_tags} == expected_tags
    # worker_id must be hashed, never the raw token.
    assert tags["worker_id"] != "install-token-abc"
    assert len(tags["worker_id"]) == 12
