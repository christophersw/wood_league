"""
Title: logging_setup.py — Loguru-based logging for the worker
Description:
    Configures loguru sinks for the wood-league-worker CLI. Long-running
    commands (``run``) truncate ``worker.log`` and emit a hardware/driver
    banner at the top of the session. Read-only commands attach to a
    secondary diagnostics sink so the run log is preserved for ``logs``.
    An :class:`_InterceptHandler` bridges stdlib ``logging`` records
    (used by third-party libraries like python-chess, httpx, urllib3)
    into the same loguru sinks as our own logger.

    Environment detection lives in :mod:`local_worker.environment` and
    banner formatting lives in :mod:`local_worker.banner`; this module
    glues them to the loguru sinks while remaining under the Halstead-
    effort quality-gate budget.

Changelog:
    2026-05-09: Initial creation (stdlib RotatingFileHandler).
    2026-05-12: Rewritten on loguru; added single-session semantics,
        diagnostics side sink, environment banner, intercept handler.
        Closes #43.
    2026-05-12: Environment detection and banner formatting moved to
        ``environment.py`` and ``banner.py`` to satisfy the Halstead-
        effort quality gate.
    2026-05-12: Library log filters wired up so routine python-chess
        ``stderr >>`` noise is downgraded to INFO, clean ``engine.quit``
        shutdowns no longer surface as WARNING, and asyncio selector
        DEBUG spam is silenced (issue #54).
    2026-05-13: log_session_banner accepts an engine_paths mapping and
        forwards it to detect_environment so the banner uses configured
        engine binaries rather than only PATH (issue #60).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import platformdirs
from loguru import logger

from local_worker._intercept import _InterceptHandler, install_intercept_handler
from local_worker._log_filters import install_library_log_filters
from local_worker.banner import format_banner_lines
from local_worker.environment import detect_environment

_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

# Loguru level names accepted for ``configure_logging`` / ``--log-level``.
_VALID_LEVELS = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}


def _log_directory() -> Path:
    """Return the platform-appropriate log directory, creating it if needed.

    Honours the ``WLW_LOG_DIR`` environment variable for tests and packagers.

    Returns:
        Absolute path to the directory in which ``worker.log`` is created.
    """
    override = os.environ.get("WLW_LOG_DIR", "").strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir("wood-league-worker", "WoodLeague")
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _normalize_level(level: str | int) -> str:
    """Coerce a user-supplied level into a canonical loguru level name.

    Args:
        level: Either a loguru level name (case-insensitive) or an int.

    Returns:
        Upper-case level name. Falls back to ``"INFO"`` for unknown values.
    """
    if isinstance(level, int):
        try:
            name = logging.getLevelName(level)
            if isinstance(name, str) and name.upper() in _VALID_LEVELS:
                return name.upper()
        except Exception:  # noqa: BLE001
            pass
        return "INFO"
    candidate = str(level).strip().upper()
    return candidate if candidate in _VALID_LEVELS else "INFO"


def _add_primary_sink(log_file: Path, level: str) -> None:
    """Reset ``log_file`` and attach the per-session loguru sink.

    Args:
        log_file: Path that will be truncated and re-opened in write mode.
        level: Normalised loguru level name.
    """
    try:
        log_file.unlink(missing_ok=True)
    except OSError:
        pass
    logger.add(
        log_file,
        level=level,
        format=_LOG_FORMAT,
        mode="w",
        encoding="utf-8",
        enqueue=False,
    )


def _add_diagnostics_sink(diagnostics_file: Path) -> None:
    """Attach the small warning-level side sink used by read-only commands.

    Args:
        diagnostics_file: Path to ``worker.diagnostics.log``.
    """
    logger.add(
        diagnostics_file,
        level="WARNING",
        format=_LOG_FORMAT,
        rotation="1 MB",
        retention=1,
        encoding="utf-8",
        enqueue=False,
    )


_current_level: str = "INFO"


def is_debug_logging() -> bool:
    """Return True if the active session is configured for DEBUG/TRACE output.

    Used by the live display to decide whether to render the "last debug log
    line" panel introduced for issue #44.
    """
    return _current_level in ("DEBUG", "TRACE")


def configure_logging(level: str = "INFO", reset_file: bool = False) -> Path:
    """Install loguru sinks for this CLI invocation.

    Args:
        level: Threshold for the primary file sink. Accepts loguru level
            names (case-insensitive).
        reset_file: If ``True``, truncate ``worker.log`` before opening it.
            Long-running commands (``run``) pass ``True``; read-only
            commands pass ``False`` so the previous session's log is
            preserved and a separate ``worker.diagnostics.log`` captures
            any warnings raised by the read-only command itself.

    Returns:
        Path to ``worker.log`` (the primary, human-readable session log).
    """
    global _current_level
    normalized = _normalize_level(level)
    _current_level = normalized
    log_dir = _log_directory()
    log_file = log_dir / "worker.log"
    diagnostics_file = log_dir / "worker.diagnostics.log"

    logger.remove()
    if reset_file:
        _add_primary_sink(log_file, normalized)
    else:
        _add_diagnostics_sink(diagnostics_file)

    install_intercept_handler(normalized)
    install_library_log_filters()
    return log_file


def log_session_banner(
    log_file: Path,
    engine_paths: dict[str, str] | None = None,
) -> None:
    """Emit the hardware/driver/engine banner at the top of a fresh session.

    Called exactly once, immediately after
    ``configure_logging(reset_file=True)`` succeeds.

    Args:
        log_file: The path returned by :func:`configure_logging`.
        engine_paths: Optional ``{"stockfish": ..., "lc0": ...}`` mapping
            from worker settings. Forwarded to :func:`detect_environment`
            so the banner reports the engine binaries the run loop will
            actually launch instead of "not found" when engines live at
            non-PATH locations (issue #60).
    """
    env = detect_environment(engine_paths)
    for line in format_banner_lines(env, log_file):
        logger.info(line)


# Backwards-compatible alias for callers that imported the private name.
_detect_environment = detect_environment


__all__ = [
    "configure_logging",
    "is_debug_logging",
    "log_session_banner",
    "_detect_environment",
    "_InterceptHandler",
]
