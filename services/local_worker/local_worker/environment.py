"""
Title: environment.py — Host/runtime probes for the worker logging banner
Description:
    Collects platform, Python, accelerator, and engine information used
    when emitting the session banner at the top of ``worker.log`` and
    (optionally) as Sentry/GlitchTip tags. Split out of
    :mod:`local_worker.logging_setup` to keep individual module Halstead
    effort below the quality-gate threshold.

Changelog:
    2026-05-12: Extracted from logging_setup.py during the cli/logging
        refactor (issue #43 follow-up).
    2026-05-12: Apple Silicon / Metal detection added so the banner is
        accurate without torch, and lc0's compiled-in ``Backend`` default
        surfaced for the engines line (issue #54).
"""
from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Any

# Captures the "DEFAULT: <backend>" token from lc0's "--help" output for the
# ``Backend`` option, e.g. ``[UCI: Backend  DEFAULT: metal  VALUES: ...]``.
_LC0_BACKEND_DEFAULT_RE = re.compile(
    r"\[UCI:\s*Backend\b[^\]]*DEFAULT:\s*([A-Za-z0-9_+-]+)"
)


def _is_apple_silicon() -> bool:
    """Return ``True`` when running on an arm64 macOS host.

    Returns:
        ``True`` if both ``platform.system()`` and ``platform.machine()``
        report an Apple Silicon configuration, ``False`` otherwise.
        Returns ``False`` on any probe error.
    """
    try:
        return platform.system() == "Darwin" and platform.machine() == "arm64"
    except Exception:  # noqa: BLE001
        return False


def _safe_call(func: Any) -> Any:
    """Call ``func`` and return its value, or ``"unknown"`` on any error.

    Args:
        func: Zero-argument callable used to probe one environment field.

    Returns:
        The function's return value, or the string ``"unknown"`` if the
        call raised any exception. Used by :func:`detect_environment`
        to keep banner generation total even when one probe fails.
    """
    try:
        return func()
    except Exception:  # noqa: BLE001 - banner must never crash startup
        return "unknown"


def _detect_torch() -> dict[str, Any]:
    """Probe for PyTorch and its GPU/MPS support.

    Returns:
        Mapping with keys ``available``, ``version``, ``cuda``, ``mps``,
        and ``gpus``. ``available`` is ``False`` when torch is not
        installed; the other fields fall back to safe defaults.
    """
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        gpus_no_torch: list[str] = (
            ["Apple Silicon (Metal-capable)"] if _is_apple_silicon() else []
        )
        return {
            "available": False,
            "version": None,
            "cuda": False,
            "mps": _is_apple_silicon(),
            "gpus": gpus_no_torch,
        }

    cuda = bool(getattr(torch.cuda, "is_available", lambda: False)())
    mps = bool(
        getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)()
    )
    gpus: list[str] = []
    if cuda:
        try:
            count = int(torch.cuda.device_count())
            gpus = [str(torch.cuda.get_device_name(i)) for i in range(count)]
        except Exception:  # noqa: BLE001
            gpus = []
    if not gpus and _is_apple_silicon() and mps:
        gpus = ["Apple Silicon (Metal-capable)"]
    return {
        "available": True,
        "version": getattr(torch, "__version__", "unknown"),
        "cuda": cuda,
        "mps": mps,
        "gpus": gpus,
    }


def _lc0_backend_default(binary: str | None) -> str | None:
    """Return lc0's compiled-in default backend name, or ``None``.

    Args:
        binary: Absolute path to the ``lc0`` binary, or ``None``.

    Returns:
        The backend name (e.g. ``"metal"``) parsed from
        ``lc0 classic --help``, or ``None`` if lc0 is missing or did not
        advertise a backend default within the 2-second budget.
    """
    if not binary:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - args are constants
            [binary, "classic", "--help"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:  # noqa: BLE001
        return None
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    match = _LC0_BACKEND_DEFAULT_RE.search(combined)
    if match:
        return match.group(1)
    return None


def _probe_engine_version(binary: str | None, args: tuple[str, ...]) -> str:
    """Run ``binary args`` once and return the first line of output.

    Args:
        binary: Absolute path to an engine binary, or ``None``.
        args: Argument tuple (e.g. ``("--version",)``) to pass to it.

    Returns:
        Short version string suitable for the banner, or ``"unknown"`` if
        the binary is missing or refuses to report a version quickly.
    """
    if not binary:
        return "unknown"

    try:
        result = subprocess.run(  # noqa: S603 - args are constants
            [binary, *args], capture_output=True, text=True, timeout=3
        )
        line = (result.stdout or result.stderr).strip().splitlines()
        return line[0] if line else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _detect_engines() -> dict[str, Any]:
    """Locate stockfish/lc0 binaries on ``PATH`` and read their versions.

    Returns:
        Mapping of engine name to ``{"path": str|None, "version": str}``.
    """
    stockfish_path = shutil.which("stockfish")
    lc0_path = shutil.which("lc0")
    return {
        "stockfish": {
            "path": stockfish_path,
            "version": _probe_engine_version(stockfish_path, ("--help",))
            if stockfish_path
            else "not found",
            "backend": None,
        },
        "lc0": {
            "path": lc0_path,
            "version": _probe_engine_version(lc0_path, ("--version",))
            if lc0_path
            else "not found",
            "backend": _lc0_backend_default(lc0_path),
        },
    }


def detect_environment() -> dict[str, Any]:
    """Probe host OS, runtime, accelerators, engine binaries.

    All OS calls go through small helpers so the banner stays total even
    when one probe fails. The result is a flat-ish dict consumed by
    :func:`local_worker.logging_setup.log_session_banner` and (optionally)
    by the telemetry tags.

    Returns:
        Dict containing host, python, torch, and engines keys.
    """
    host = {
        "system": _safe_call(platform.system),
        "release": _safe_call(platform.release),
        "machine": _safe_call(platform.machine),
    }
    python_info = {
        "version": _safe_call(platform.python_version),
        "implementation": _safe_call(platform.python_implementation),
    }
    return {
        "host": host,
        "python": python_info,
        "torch": _detect_torch(),
        "engines": _detect_engines(),
    }


__all__ = ["detect_environment"]
