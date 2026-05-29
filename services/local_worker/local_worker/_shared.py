"""
Title: _shared.py — Shared CLI helpers and constants
Description:
    Tiny objects reused across multiple ``local_worker.commands.*`` modules:
    a single :class:`rich.console.Console`, an installed-version probe, and
    the user-data directory resolver.  Centralising them keeps each command
    module's Halstead effort low and prevents drift across copies.

Changelog:
    2026-05-12: Initial creation. Issue #43 follow-up.
    2026-05-14: ``data_dir()`` honours the ``WLW_DATA_DIR`` env var so the
        worker can keep eval-cache + tuner state on a RunPod volume (#79).
    2026-05-28: ``read_gpu_count()`` exposes the ``WL_GPU_COUNT`` the vast
        entrypoint detects, so both the SF fan-out and lc0 self-sizing
        scale to the one-lc0-per-GPU launch (#223).
"""
from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

import platformdirs
from rich.console import Console

# Subcommand names that produce long-running worker sessions. These are
# the only commands that (a) truncate ``worker.log`` and emit a fresh
# session banner, and (b) initialise telemetry when consent is on.
LONG_RUNNING_COMMANDS: set[str] = {"run"}

# A single, shared Rich console used by every command module.
console = Console()


def current_release() -> str:
    """Return the installed package version, or ``"source"`` when editable.

    Returns:
        Release tag string used by Sentry/GlitchTip ``release`` filtering.
    """
    try:
        return _pkg_version("wood-league-worker")
    except PackageNotFoundError:
        return "source"


def data_dir() -> Path:
    """Return the platform user-data directory for this worker.

    If the ``WLW_DATA_DIR`` environment variable is set and non-empty, that
    path is used verbatim instead of the platform default. This lets a
    containerised deployment (e.g. RunPod) park the eval cache and tuner
    state on a mounted volume.

    Returns:
        Path to the writable data directory; created if absent.
    """
    override = os.environ.get("WLW_DATA_DIR", "").strip()
    if override:
        path = Path(override)
    else:
        path = Path(platformdirs.user_data_dir("wood-league-worker", "WoodLeague"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_gpu_count() -> int:
    """Number of GPUs on this host (hence concurrent lc0 processes).

    ``vast/onstart.sh`` detects the GPU count with ``nvidia-smi`` and
    exports it as ``WL_GPU_COUNT``. One lc0 process runs per GPU (#223),
    so this doubles as the lc0 process count used to scale both the
    Stockfish fan-out reservation and each lc0 process's own CPU/RAM
    self-sizing. A missing, non-numeric, or non-positive value falls back
    to a single GPU.

    Returns:
        GPU count as an int >= 1.
    """
    raw = os.environ.get("WL_GPU_COUNT", "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 1
    return parsed if parsed >= 1 else 1
