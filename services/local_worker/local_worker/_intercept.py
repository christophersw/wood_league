"""
Title: _intercept.py — stdlib-to-loguru bridge handler
Description:
    Houses :class:`_InterceptHandler` and its installer so that the main
    ``logging_setup`` module stays well under the project's Halstead-
    effort budget. Loguru recommends installing one of these as the root
    handler so that third-party libraries emitting via stdlib ``logging``
    (python-chess, httpx, urllib3) end up in the same sink and respect
    the same formatting and level threshold as our own logger calls.

Changelog:
    2026-05-12: Extracted from logging_setup.py (issue #43 follow-up).
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

from loguru import logger


class _InterceptHandler(logging.Handler):
    """Forward stdlib ``logging`` records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - stdlib API
        """Translate a stdlib ``LogRecord`` into a loguru log call.

        Args:
            record: The stdlib record produced by another library.
        """
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame: Optional[Any] = inspect.currentframe()
        depth = 0
        while frame is not None:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def install_intercept_handler(level: str) -> None:
    """Replace stdlib root handlers with one :class:`_InterceptHandler`.

    Args:
        level: Threshold name to apply to the stdlib root logger; loguru
            sinks still apply their own level filters on top of this.
    """
    handler = _InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))


__all__ = ["_InterceptHandler", "install_intercept_handler"]
