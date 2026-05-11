"""
Title: logging_setup.py — File-based logging for the worker
Description:
    Configures a rotating file handler that writes warnings and errors to a
    platform-standard log directory. Console output is left to Rich.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import platformdirs


def configure_logging(log_dir: str = "") -> Path:
    """Set up a rotating file log at the platform log directory.

    Args:
        log_dir: Override path for log directory. Defaults to platform log dir.

    Returns:
        Path to the log file.
    """
    if log_dir:
        log_path = Path(log_dir)
    else:
        log_path = Path(platformdirs.user_log_dir("wood-league-worker", "WoodLeague"))
    log_path.mkdir(parents=True, exist_ok=True)
    log_file = log_path / "worker.log"

    handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s — %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    return log_file
