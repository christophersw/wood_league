"""
Title: cli.py — Typer CLI entry point for wood-league-worker
Description:
    Constructs the top-level Typer ``app``, wires global options
    (``--log-level``, ``--telemetry``/``--no-telemetry``, ``WLW_LOG_DIR``),
    and registers commands implemented in sibling modules under
    :mod:`local_worker.commands`. Keeping this module a thin wiring layer
    keeps Halstead effort well below the project quality-gate threshold.

Changelog:
    2026-05-09: Initial creation
    2026-05-10: Added BT4 network and Syzygy download helpers in setup;
        fix Syzygy URL (3-4-5-wdl subdir)
    2026-05-12: Rewrote ``logs`` as a Python-native tail (closes #43);
        wired loguru-based logging, --log-level, telemetry flags and
        ``telemetry`` sub-app.
    2026-05-12: Split per-command code into ``local_worker.commands.*``
        modules; this file is now just construction + wiring.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from local_worker._shared import LONG_RUNNING_COMMANDS, current_release
from local_worker.commands import analyze as analyze_cmd
from local_worker.commands import info as info_cmd
from local_worker.commands import logs as logs_cmd
from local_worker.commands import run as run_cmd
from local_worker.commands import setup as setup_cmd
from local_worker.commands.logs import _tail_lines  # re-exported for tests
from local_worker.commands.telemetry import telemetry_app
from local_worker.config import load_settings
from local_worker.environment import detect_environment
from local_worker.logging_setup import configure_logging, log_session_banner
from local_worker.telemetry import (
    default_config_path as _telemetry_config_path,
    get_consent,
    init_telemetry,
    prompt_for_consent,
)

app = typer.Typer(
    name="wood-league-worker",
    help="Local analysis worker for the Wood League chess platform.",
    no_args_is_help=True,
)
app.add_typer(telemetry_app, name="telemetry")


def _effective_telemetry(override: Optional[bool], config_path: Path) -> bool:
    """Resolve effective telemetry state given the CLI override and config.

    Args:
        override: ``True`` from ``--telemetry``, ``False`` from
            ``--no-telemetry``, or ``None`` if neither flag was passed.
        config_path: Path to the worker config file.

    Returns:
        Effective consent value to feed into :func:`init_telemetry`.
    """
    if override is not None:
        return override
    persisted = get_consent(config_path)
    if persisted is None:
        return prompt_for_consent(config_path)
    return persisted


@app.callback()
def _startup(
    ctx: typer.Context,
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        envvar="WOOD_LEAGUE_LOG_LEVEL",
        help="Logging threshold (TRACE/DEBUG/INFO/WARNING/ERROR/CRITICAL).",
    ),
    telemetry: Optional[bool] = typer.Option(
        None,
        "--telemetry/--no-telemetry",
        help="Override persisted telemetry consent for this invocation.",
    ),
    log_dir: str = typer.Option(
        "",
        envvar="WLW_LOG_DIR",
        help="Override log file directory (hidden, intended for tests).",
        hidden=True,
    ),
) -> None:
    """Configure logging and optional telemetry on every invocation."""
    if log_dir:
        os.environ["WLW_LOG_DIR"] = log_dir

    is_long_running = ctx.invoked_subcommand in LONG_RUNNING_COMMANDS
    log_file = configure_logging(level=log_level, reset_file=is_long_running)
    if is_long_running:
        log_session_banner(log_file)
        config_path = _telemetry_config_path()
        consent = _effective_telemetry(telemetry, config_path)
        init_telemetry(
            consent=consent,
            release=current_release(),
            environment_info=detect_environment(),
            worker_id=load_settings().worker_id,
            log_level=log_level,
        )


# Register subcommands from sibling modules.
app.command()(setup_cmd.setup)
app.command()(run_cmd.run)
app.command()(analyze_cmd.analyze)
app.command()(logs_cmd.logs)
app.command()(info_cmd.version)
app.command()(info_cmd.status)


__all__ = ["app", "_tail_lines"]
