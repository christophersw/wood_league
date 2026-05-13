"""
Title: test_environment.py — Unit tests for the environment-detection helpers
Description:
    Covers ``local_worker.environment.detect_environment`` and its safe-call
    fallback behaviour. Split out of ``test_logging_setup.py`` so each test
    module stays under the Halstead-effort budget.

Changelog:
    2026-05-12: Extracted from test_logging_setup.py (issue #43 follow-up).
"""
from __future__ import annotations

import pytest

from local_worker import environment
from local_worker.environment import detect_environment


def test_detect_environment_dict_shape() -> None:
    """The detector must return the documented top-level keys."""
    env = detect_environment()
    assert set(env.keys()) >= {"host", "python", "torch", "engines"}
    assert "system" in env["host"]
    assert "version" in env["python"]
    assert "available" in env["torch"]
    assert "stockfish" in env["engines"]


def test_detect_environment_unknown_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a probe raises, the value should degrade to 'unknown'."""
    def boom() -> str:
        raise RuntimeError("no probe for you")

    monkeypatch.setattr(environment.platform, "system", boom)
    env = detect_environment()
    assert env["host"]["system"] == "unknown"
