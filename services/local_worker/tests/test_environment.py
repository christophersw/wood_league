"""
Title: test_environment.py — Unit tests for the environment-detection helpers
Description:
    Covers ``local_worker.environment.detect_environment`` and its safe-call
    fallback behaviour, plus the Apple-Silicon / Metal probe used for the
    banner.

Changelog:
    2026-05-12: Extracted from test_logging_setup.py (issue #43 follow-up).
    2026-05-12: Coverage added for Apple Silicon detection and the lc0
        backend probe (issue #54).
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


def test_detect_torch_reports_apple_silicon_when_torch_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without torch, Apple Silicon should still surface in the banner."""
    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str, globals=None, locals=None, fromlist=(), level=0
    ):
        if name == "torch":
            raise ImportError("torch not installed for this test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(environment.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(environment.platform, "machine", lambda: "arm64")

    torch_info = environment._detect_torch()
    assert torch_info["available"] is False
    assert torch_info["mps"] is True
    assert torch_info["gpus"] == ["Apple Silicon (Metal-capable)"]


def test_detect_torch_no_gpus_off_apple_silicon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On non-Apple hosts with no torch we should still report no GPUs."""
    import builtins

    real_import = builtins.__import__

    def fake_import(
        name: str, globals=None, locals=None, fromlist=(), level=0
    ):
        if name == "torch":
            raise ImportError("torch not installed for this test")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(environment.platform, "system", lambda: "Linux")
    monkeypatch.setattr(environment.platform, "machine", lambda: "x86_64")

    torch_info = environment._detect_torch()
    assert torch_info["available"] is False
    assert torch_info["mps"] is False
    assert torch_info["gpus"] == []


def test_lc0_backend_default_parsed_from_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The backend default should be parsed out of lc0's --help output."""
    sample = (
        "  -b,  --backend=CHOICE\n"
        "               Neural network computational backend to use.\n"
        "               [UCI: Backend  DEFAULT: metal  VALUES: metal,blas]\n"
    )

    class FakeResult:
        stdout = sample
        stderr = ""

    def fake_run(*args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    assert environment._lc0_backend_default("/fake/lc0") == "metal"


def test_lc0_backend_default_none_when_binary_missing() -> None:
    """No binary means no backend, never a crash."""
    assert environment._lc0_backend_default(None) is None
