"""
Title: test_log_filters.py — Unit tests for python-chess log filters
Description:
    Verifies that the noise-reduction filters installed by
    :func:`local_worker._log_filters.install_library_log_filters`
    downgrade routine engine-stderr lines while leaving genuine errors
    untouched.

Changelog:
    2026-05-12: Initial creation. Issue #54 fix 4.
"""
from __future__ import annotations

import logging

from local_worker._log_filters import (
    ChessEngineStderrFilter,
    install_library_log_filters,
)


def _make_record(level: int, message: str) -> logging.LogRecord:
    """Build a stdlib ``LogRecord`` carrying ``message`` at ``level``.

    Args:
        level: Numeric stdlib logging level (e.g. ``logging.WARNING``).
        message: Already-formatted message text.

    Returns:
        A fresh ``LogRecord`` suitable for direct filter testing.
    """
    return logging.LogRecord(
        name="chess.engine",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_stderr_filter_downgrades_informational_lc0_lines() -> None:
    """Routine lc0 stderr chatter must drop from WARNING to INFO."""
    record = _make_record(
        logging.WARNING,
        "<UciProtocol (pid=12345)>: stderr >> "
        "Found 35 WDL, 0 DTM and 35 DTZ tablebase files",
    )
    assert ChessEngineStderrFilter().filter(record) is True
    assert record.levelno == logging.INFO
    assert record.levelname == "INFO"


def test_stderr_filter_keeps_error_like_stderr_at_warning() -> None:
    """Error keywords in stderr lines must remain at WARNING."""
    record = _make_record(
        logging.WARNING,
        "<UciProtocol (pid=12345)>: stderr >> FATAL: failed to load weights",
    )
    assert ChessEngineStderrFilter().filter(record) is True
    assert record.levelno == logging.WARNING


def test_stderr_filter_ignores_non_stderr_warnings() -> None:
    """Library warnings without the stderr-relay prefix pass through."""
    record = _make_record(
        logging.WARNING,
        "Not transmitting history with null moves to UCI engine",
    )
    assert ChessEngineStderrFilter().filter(record) is True
    assert record.levelno == logging.WARNING


def test_install_library_log_filters_is_idempotent() -> None:
    """Repeated installs must not stack duplicate filters."""
    install_library_log_filters()
    install_library_log_filters()
    chess_filters = [
        f
        for f in logging.getLogger("chess.engine").filters
        if isinstance(f, ChessEngineStderrFilter)
    ]
    assert len(chess_filters) == 1
