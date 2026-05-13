"""
Title: _log_filters.py — stdlib ``logging.Filter`` rules for noisy libraries
Description:
    python-chess relays every line an engine writes to stderr through its
    ``chess.engine`` logger at WARNING. For lc0 that means weight-loading
    notices, tablebase counts, and backend init messages all surface as
    warnings even though they are purely informational. The filters in
    this module drop or downgrade those records before they reach our
    loguru sink, while leaving genuinely error-like messages untouched.

    Installed from :func:`local_worker.logging_setup.configure_logging`.

Changelog:
    2026-05-12: Initial creation — downgrade python-chess engine-stderr
        WARNINGs to INFO (issue #54, fix 4).
    2026-05-12: Added ``ChessEngineCleanExitFilter`` so the
        ``engine process died unexpectedly (exit code: -2)`` line that
        follows our own clean ``engine.quit()`` no longer surfaces as
        a WARNING (issue #54, fix 5).
"""
from __future__ import annotations

import logging
import re

# Substrings that signal a real problem in an engine stderr line. Matched
# case-insensitively against the formatted record message.
_ERROR_LIKE_TOKENS: tuple[str, ...] = (
    "error",
    "fail",
    "exception",
    "traceback",
    "fatal",
    "abort",
    "segfault",
)

# Matches the stderr-relay prefix python-chess emits for each line that lc0
# (or any UCI engine) writes to its stderr, e.g.
# ``<UciProtocol (pid=12345)>: stderr >> Found 35 WDL ...``.
_STDERR_PREFIX_RE = re.compile(r"^<[^>]+>:\s*stderr\s*>>", re.IGNORECASE)

# Exit codes that indicate a clean shutdown initiated by our analysis code
# calling ``engine.quit()``. python-chess sends SIGINT (signal 2, exit -2)
# during a normal quit; ``0`` is a graceful exit; ``None`` is sometimes
# reported when python-chess hasn't read the final code.
_CLEAN_EXIT_CODES = ("-2", "0", "None")

# Matches python-chess shutdown messages that report an exit code. The
# capture group on the code lets us decide whether to downgrade.
_CLEAN_EXIT_RE = re.compile(
    r"(engine process died unexpectedly|Connection lost"
    r"|Closing analysis because engine has been terminated)"
    r".*\(exit code:\s*(-?\d+|None)",
    re.IGNORECASE,
)


def _is_error_like(message: str) -> bool:
    """Return ``True`` when ``message`` contains an error-style keyword.

    Args:
        message: Already-formatted log record message.

    Returns:
        ``True`` when at least one of the error-like tokens
        (``error``, ``fail``, ``exception``, ...) appears in the message,
        regardless of case. ``False`` for informational engine chatter.
    """
    lowered = message.lower()
    return any(token in lowered for token in _ERROR_LIKE_TOKENS)


class ChessEngineStderrFilter(logging.Filter):
    """Downgrade routine ``stderr >>`` chatter from python-chess to INFO.

    Records that did not originate from the engine-stderr relay (i.e. the
    message does not start with the ``<...>: stderr >>`` prefix) are
    forwarded unchanged so genuine library warnings still reach the user.
    Records whose message also matches an error-like keyword keep their
    WARNING level so real engine problems remain loud.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Mutate ``record.levelno`` in place when appropriate.

        Args:
            record: The stdlib log record passing through the filter.

        Returns:
            ``True`` so the record is always emitted; only its level
            (and ``levelname``) may be rewritten.
        """
        if record.levelno != logging.WARNING:
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let a filter raise
            return True
        if not _STDERR_PREFIX_RE.search(message):
            return True
        if _is_error_like(message):
            return True
        record.levelno = logging.INFO
        record.levelname = "INFO"
        return True


class ChessEngineCleanExitFilter(logging.Filter):
    """Downgrade python-chess shutdown WARNINGs that follow our own quit.

    python-chess emits ``engine process died unexpectedly (exit code: -2)``
    at WARNING after our analysis code cleanly calls ``engine.quit()``,
    because the library shuts the engine down via SIGINT (signal 2 →
    exit ``-2``). The line is alarming and useless. We detect the
    specific message and demote it to DEBUG when the exit code matches
    one of our known clean-shutdown codes.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Demote known clean-shutdown shutdown messages to DEBUG.

        Args:
            record: The stdlib log record passing through the filter.

        Returns:
            ``True`` so the record is always emitted; only its level
            (and ``levelname``) may be rewritten.
        """
        if record.levelno != logging.WARNING:
            return True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        match = _CLEAN_EXIT_RE.search(message)
        if not match:
            return True
        if match.group(2) in _CLEAN_EXIT_CODES:
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


def install_library_log_filters() -> None:
    """Attach the python-chess noise filters to the right loggers.

    Idempotent — repeated calls do not stack duplicate filters because we
    check each logger's existing filter classes before adding ours. Also
    raises ``asyncio``'s logger to INFO so the per-loop
    ``Using selector: KqueueSelector`` DEBUG spam never reaches our sinks.
    Safe to call from every ``configure_logging`` invocation.
    """
    chess_engine = logging.getLogger("chess.engine")
    _ensure_filter(chess_engine, ChessEngineStderrFilter)
    _ensure_filter(chess_engine, ChessEngineCleanExitFilter)
    # asyncio.selector_events logs a DEBUG line on every event-loop
    # creation. Lift the whole asyncio tree to INFO; we never want its
    # internals in our worker logs.
    logging.getLogger("asyncio").setLevel(logging.INFO)


def _ensure_filter(
    target: logging.Logger, filter_cls: type[logging.Filter]
) -> None:
    """Attach one instance of ``filter_cls`` to ``target`` if missing.

    Args:
        target: The stdlib logger that should run the filter on emit.
        filter_cls: Concrete filter class to instantiate when no existing
            filter of the same type is attached.
    """
    if any(isinstance(existing, filter_cls) for existing in target.filters):
        return
    target.addFilter(filter_cls())


__all__ = [
    "ChessEngineStderrFilter",
    "ChessEngineCleanExitFilter",
    "install_library_log_filters",
]
