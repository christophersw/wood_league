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
    2026-05-12: Added coverage for ANSI stripping and the UCI ``id name``
        preference applied to engine version probes (issue #54).
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


def test_strip_ansi_removes_color_codes() -> None:
    """The ANSI helper must drop CSI colour sequences."""
    sample = "\x1b[1m\x1b[31m       _\x1b[0m v0.32.1 built today"
    assert environment._strip_ansi(sample) == "       _ v0.32.1 built today"


def test_probe_engine_version_prefers_id_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UCI ``id name`` line should win over the binary's banner."""

    def fake_uci_id_name(binary: str) -> str | None:
        assert binary == "/fake/stockfish"
        return "Stockfish 16.1"

    def fake_run(*args, **kwargs):  # pragma: no cover - guards against use
        raise AssertionError("fallback should not be needed when id name works")

    monkeypatch.setattr(environment, "_uci_id_name", fake_uci_id_name)
    monkeypatch.setattr(environment.subprocess, "run", fake_run)
    assert (
        environment._probe_engine_version("/fake/stockfish", ("--help",))
        == "Stockfish 16.1"
    )


def test_resolve_engine_path_prefers_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Configured paths win over shutil.which when the binary exists (issue #60)."""
    fake = tmp_path / "lc0"
    fake.write_text("")  # exists() is what matters
    called: list[str] = []

    def _track(name: str) -> str:
        called.append(name)
        return "/usr/bin/lc0"

    monkeypatch.setattr(environment.shutil, "which", _track)
    assert environment._resolve_engine_path(str(fake), "lc0") == str(fake)
    assert called == []  # PATH fallback must not run when configured path exists


def test_resolve_engine_path_falls_back_to_path_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty configured path means: try shutil.which (issue #60 acceptance)."""
    monkeypatch.setattr(environment.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert environment._resolve_engine_path("", "stockfish") == "/usr/bin/stockfish"
    assert environment._resolve_engine_path(None, "lc0") == "/usr/bin/lc0"


def test_resolve_engine_path_returns_none_when_configured_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A configured but non-existent path returns None — banner says 'not found'."""
    monkeypatch.setattr(environment.shutil, "which", lambda _name: "/usr/bin/lc0")
    missing = tmp_path / "nope" / "lc0.exe"
    # Do NOT fall back to shutil.which: if the user configured a path, it
    # is what the run loop will launch; reporting the PATH binary would
    # be misleading.
    assert environment._resolve_engine_path(str(missing), "lc0") is None


def test_detect_engines_uses_configured_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """End-to-end: configured paths flow through _detect_engines (issue #60)."""
    sf = tmp_path / "stockfish.exe"
    sf.write_text("")
    lc = tmp_path / "lc0.exe"
    lc.write_text("")
    monkeypatch.setattr(environment, "_probe_engine_version", lambda b, _a: f"v@{b}")
    monkeypatch.setattr(environment, "_lc0_backend_default", lambda _b: "cuda-fp16")
    monkeypatch.setattr(environment.shutil, "which", lambda _n: None)

    engines = environment._detect_engines(
        {"stockfish": str(sf), "lc0": str(lc)},
    )
    assert engines["stockfish"]["path"] == str(sf)
    assert engines["stockfish"]["version"] == f"v@{sf}"
    assert engines["lc0"]["path"] == str(lc)
    assert engines["lc0"]["backend"] == "cuda-fp16"


def test_detect_environment_threads_engine_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """detect_environment passes engine_paths through to _detect_engines."""
    sf = tmp_path / "stockfish"
    sf.write_text("")
    monkeypatch.setattr(environment, "_probe_engine_version", lambda b, _a: "fake")
    monkeypatch.setattr(environment, "_lc0_backend_default", lambda _b: None)
    monkeypatch.setattr(environment.shutil, "which", lambda _n: None)

    env = detect_environment({"stockfish": str(sf)})
    assert env["engines"]["stockfish"]["path"] == str(sf)
    assert env["engines"]["lc0"]["path"] is None  # unconfigured + not on PATH


def test_probe_engine_version_strips_ansi_from_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If UCI handshake fails, ANSI escapes must not leak into the banner."""

    class FakeResult:
        stdout = "\x1b[1m\x1b[31m       _\x1b[0m\nlc0 v0.32.1+git.dirty\n"
        stderr = ""

    monkeypatch.setattr(environment, "_uci_id_name", lambda _b: None)
    monkeypatch.setattr(
        environment.subprocess, "run", lambda *a, **k: FakeResult()
    )
    result = environment._probe_engine_version("/fake/lc0", ("--version",))
    assert "\x1b" not in result
    # The first non-blank line after ANSI stripping is used.
    assert result.startswith("_") or "lc0" in result
