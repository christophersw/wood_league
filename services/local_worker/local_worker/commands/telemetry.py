"""
Title: telemetry.py — ``wood-league-worker telemetry`` sub-app
Description:
    Implements the ``status``/``enable``/``disable`` commands that manage
    the persisted log-upload consent flag. The subcommand name stays
    ``telemetry`` for backward compatibility with installed shell
    completions and any user muscle memory, but the help text now talks
    about log upload rather than GlitchTip.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
    2026-05-13 (#52): Re-pointed at the new log-upload consent module;
        rewrote help text to remove all GlitchTip references.
"""
from __future__ import annotations

import typer

from local_worker._shared import console
from local_worker.consent import (
    default_config_path as _consent_config_path,
    get_consent,
    set_consent,
)

telemetry_app = typer.Typer(
    name="telemetry",
    help="Manage the worker's log-upload consent.",
    no_args_is_help=True,
)


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show the current log-upload consent state."""
    config_path = _consent_config_path()
    consent = get_consent(config_path)
    if consent is None:
        console.print(
            "[yellow]Log upload: not configured (will prompt on next `run`)."
        )
    elif consent:
        console.print("[green]Log upload: enabled.")
    else:
        console.print("[red]Log upload: disabled.")
    console.print(f"[dim]Config file: {config_path}")


@telemetry_app.command("enable")
def telemetry_enable() -> None:
    """Opt in to uploading session logs to the Wood League maintainers."""
    config_path = _consent_config_path()
    set_consent(config_path, True)
    console.print("[green]Log upload enabled.")


@telemetry_app.command("disable")
def telemetry_disable() -> None:
    """Opt out of uploading session logs."""
    config_path = _consent_config_path()
    set_consent(config_path, False)
    console.print("[yellow]Log upload disabled.")
