"""
Title: _crash_hook.py — Worker excepthook that offers a log upload
Description:
    Installs a ``sys.excepthook`` replacement that prints the traceback
    and (when consent is on) prompts the user to upload the current
    ``worker.log`` via :func:`local_worker.log_upload.upload_log`.

Changelog:
    2026-05-13 (#52): Initial creation, split from log_upload.py to
        keep each module under the Halstead-effort gate.
"""
from __future__ import annotations

import sys
import traceback
from types import TracebackType
from typing import Optional

from local_worker.consent import get_consent


def _ask_upload() -> bool:
    """Prompt the user once for permission to upload the crash log.

    Returns:
        ``True`` if the user accepts (default), ``False`` otherwise.
    """
    try:
        answer = input('Upload this crash log to maintainers? [Y/n] ').strip().lower()
    except EOFError:
        return False
    return answer in {'', 'y', 'yes'}


def _crash_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> None:
    """``sys.excepthook`` replacement that offers an interactive upload.

    Args:
        exc_type: Exception class.
        exc_value: Exception instance.
        exc_traceback: Traceback object (may be ``None``).
    """
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    if get_consent() is not True:
        return
    if not _ask_upload():
        return
    # Local import dodges the circular dep between log_upload <-> _crash_hook.
    from local_worker.log_upload import upload_log

    upload_id = upload_log('crash', note=f'{exc_type.__name__}: {exc_value}'[:4096])
    if upload_id > 0:
        print(f'Uploaded crash log (id={upload_id}).', file=sys.stderr)


def install_crash_hook() -> None:
    """Install :func:`_crash_excepthook` as ``sys.excepthook``."""
    sys.excepthook = _crash_excepthook


__all__ = ['install_crash_hook']
