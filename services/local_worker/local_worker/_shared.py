"""
Title: _shared.py — Shared CLI helpers and constants
Description:
    Tiny objects reused across multiple ``local_worker.commands.*`` modules:
    a single :class:`rich.console.Console`, an installed-version probe, and
    the user-data directory resolver.  Centralising them keeps each command
    module's Halstead effort low and prevents drift across copies.

Changelog:
    2026-05-12: Initial creation. Issue #43 follow-up.
"""
from __future__ import annotations

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

    Returns:
        Path to the writable data directory; created if absent.
    """
    path = Path(platformdirs.user_data_dir("wood-league-worker", "WoodLeague"))
    path.mkdir(parents=True, exist_ok=True)
    return path
