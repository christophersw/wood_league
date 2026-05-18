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
    2026-05-13 (#52): Replaced GlitchTip telemetry init with the new
        log-upload consent prompt + crash-hook installer; registered
        the ``submit-log`` subcommand.
    2026-05-16: Registered ``cache-merge`` subcommand for offline delta merge.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

from local_worker._shared import LONG_RUNNING_COMMANDS
from local_worker.commands import analyze as analyze_cmd
from local_worker.commands import cache_merge_cmd
from local_worker.commands import info as info_cmd
from local_worker.commands import lc0_tuning_pull_cmd
from local_worker.commands import logs as logs_cmd
from local_worker.commands import plan_sf_fanout_cmd
from local_worker.commands import run as run_cmd
from local_worker.commands import setup as setup_cmd
from local_worker.commands import submit_log as submit_log_cmd
from local_worker.commands.logs import _tail_lines  # re-exported for tests
from local_worker.commands.telemetry import telemetry_app
from local_worker.consent import (
    default_config_path as _consent_config_path,
    get_consent,
    prompt_for_consent,
)
from local_worker.log_upload import install_crash_hook
from local_worker.config import load_settings
from local_worker.logging_setup import configure_logging, log_session_banner

app = typer.Typer(
    name="wood-league-worker",
    help="Local analysis worker for the Wood League chess platform.",
    no_args_is_help=True,
)
app.add_typer(telemetry_app, name="telemetry")


def _configured_engine_paths() -> dict[str, str]:
    """Return the stockfish/lc0 paths from persisted settings, if any.

    Used by the session-banner logger so the diagnostic line reflects the
    engines the run loop will actually launch (issue #60). Errors loading
    settings are swallowed because the banner must never crash startup.

    Returns:
        Mapping with optional ``"stockfish"`` and ``"lc0"`` keys. Empty
        when settings cannot be read or neither path is configured.
    """
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - banner must be total
        return {}
    paths: dict[str, str] = {}
    if settings.stockfish_path:
        paths["stockfish"] = settings.stockfish_path
    if settings.lc0_path:
        paths["lc0"] = settings.lc0_path
    return paths


def _effective_consent(override: Optional[bool], config_path: Path) -> bool:
    """Resolve effective log-upload consent for this invocation.

    Args:
        override: ``True`` from ``--telemetry``, ``False`` from
            ``--no-telemetry``, or ``None`` if neither flag was passed.
        config_path: Path to the worker consent config file.

    Returns:
        Effective consent value to use for crash-hook installation.
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
        help="Override persisted log-upload consent for this invocation.",
    ),
    log_dir: str = typer.Option(
        "",
        envvar="WLW_LOG_DIR",
        help="Override log file directory (hidden, intended for tests).",
        hidden=True,
    ),
) -> None:
    """Configure logging and (optionally) install the crash-upload hook."""
    if log_dir:
        os.environ["WLW_LOG_DIR"] = log_dir

    is_long_running = ctx.invoked_subcommand in LONG_RUNNING_COMMANDS
    log_file = configure_logging(level=log_level, reset_file=is_long_running)
    if is_long_running:
        log_session_banner(log_file, engine_paths=_configured_engine_paths())
        config_path = _consent_config_path()
        if _effective_consent(telemetry, config_path):
            install_crash_hook()


# Register subcommands from sibling modules.
app.command()(setup_cmd.setup)
app.command()(run_cmd.run)
app.command()(analyze_cmd.analyze)
app.command()(logs_cmd.logs)
app.command()(info_cmd.version)
app.command()(info_cmd.status)
app.command("submit-log")(submit_log_cmd.submit_log)
app.command("cache-merge")(cache_merge_cmd.cache_merge)
app.command("plan-sf-fanout")(plan_sf_fanout_cmd.plan_sf_fanout)
app.command("lc0-tuning-pull")(lc0_tuning_pull_cmd.lc0_tuning_pull)


__all__ = ["app", "_tail_lines"]
