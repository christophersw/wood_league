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


def install_library_log_filters() -> None:
    """Attach the python-chess noise filters to the right loggers.

    Idempotent — repeated calls do not stack duplicate filters because we
    check each logger's existing filter classes before adding ours. Safe
    to call from every ``configure_logging`` invocation.
    """
    _ensure_filter(logging.getLogger("chess.engine"), ChessEngineStderrFilter)


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
    "install_library_log_filters",
]
