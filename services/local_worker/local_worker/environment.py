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
"""
from __future__ import annotations

import platform
import shutil
from typing import Any


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
        return {"available": False, "version": None, "cuda": False, "mps": False, "gpus": []}

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
    return {
        "available": True,
        "version": getattr(torch, "__version__", "unknown"),
        "cuda": cuda,
        "mps": mps,
        "gpus": gpus,
    }


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
    import subprocess  # local import keeps cold-import cost down

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
        },
        "lc0": {
            "path": lc0_path,
            "version": _probe_engine_version(lc0_path, ("--version",))
            if lc0_path
            else "not found",
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
