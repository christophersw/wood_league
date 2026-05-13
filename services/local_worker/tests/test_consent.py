"""
Title: test_consent.py — Log-upload consent persistence tests
Description:
    Covers the JSON-backed consent persistence module, including the
    one-release migration path from the legacy ``telemetry`` key.

Changelog:
    2026-05-13 (#52): Initial creation. Replaces test_telemetry.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_worker.consent import (
    get_consent,
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


def test_set_consent_persists_new_key(config_path: Path) -> None:
    """``set_consent`` writes the new ``log_upload_consent`` key."""
    set_consent(config_path, True)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["log_upload_consent"] is True
    assert "asked_at" in data
    assert get_consent(config_path) is True


def test_set_consent_drops_legacy_key(config_path: Path) -> None:
    """A pre-existing ``telemetry`` key is removed on write."""
    config_path.write_text(json.dumps({"telemetry": True}), encoding="utf-8")
    set_consent(config_path, False)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert "telemetry" not in data
    assert data["log_upload_consent"] is False


def test_get_consent_reads_legacy_key(config_path: Path) -> None:
    """A legacy ``telemetry`` value is honoured for one release."""
    config_path.write_text(json.dumps({"telemetry": True}), encoding="utf-8")
    assert get_consent(config_path) is True


def test_prompt_for_consent_yes(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``y`` answer opts the user in and persists the choice."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    assert prompt_for_consent(config_path) is True
    # Second call must short-circuit on the persisted value.
    monkeypatch.setattr("builtins.input", lambda _prompt="": (_ for _ in ()).throw(
        AssertionError("should not re-prompt")
    ))
    assert prompt_for_consent(config_path) is True


def test_prompt_for_consent_defaults_to_no(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input persists an explicit ``False``."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    assert prompt_for_consent(config_path) is False
    assert get_consent(config_path) is False


def test_prompt_for_consent_help_then_yes(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``?`` answer prints help and re-prompts."""
    answers = iter(["?", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert prompt_for_consent(config_path) is True


def test_prompt_for_consent_handles_eof(
    config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed stdin opts out (does not crash)."""
    def raise_eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    assert prompt_for_consent(config_path) is False
