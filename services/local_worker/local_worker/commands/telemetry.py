"""
Title: telemetry.py — ``wood-league-worker telemetry`` sub-app
Description:
    Implements the ``status``/``enable``/``disable`` commands that manage
    persisted GlitchTip telemetry consent.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
"""
from __future__ import annotations

import typer

from local_worker._shared import console
from local_worker.telemetry import (
    default_config_path as _telemetry_config_path,
    get_consent,
    set_consent,
)

telemetry_app = typer.Typer(
    name="telemetry",
    help="Manage opt-in remote diagnostics (GlitchTip).",
    no_args_is_help=True,
)


@telemetry_app.command("status")
def telemetry_status() -> None:
    """Show the current telemetry consent state."""
    config_path = _telemetry_config_path()
    consent = get_consent(config_path)
    if consent is None:
        console.print("[yellow]Telemetry: not configured (will prompt on next `run`).")
    elif consent:
        console.print("[green]Telemetry: enabled.")
    else:
        console.print("[red]Telemetry: disabled.")
    console.print(f"[dim]Config file: {config_path}")


@telemetry_app.command("enable")
def telemetry_enable() -> None:
    """Opt in to sending anonymous diagnostics to GlitchTip."""
    config_path = _telemetry_config_path()
    set_consent(config_path, True)
    console.print("[green]Telemetry enabled.")


@telemetry_app.command("disable")
def telemetry_disable() -> None:
    """Opt out of sending diagnostics to GlitchTip."""
    config_path = _telemetry_config_path()
    set_consent(config_path, False)
    console.print("[yellow]Telemetry disabled.")
