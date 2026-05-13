"""
Title: log_upload.py — Worker session-log uploader
Description:
    Reads the current ``worker.log`` and POSTs it to the Wood League
    server's ``/api/v1/worker/logs/`` endpoint as a multipart upload.
    Wraps both the interactive ``submit-log`` flow and the auto-upload
    invoked by the :func:`install_crash_hook` ``sys.excepthook``. All
    failures are caught locally: a network error never propagates out
    and never crashes the running worker.

Changelog:
    2026-05-13 (#52): Initial creation. Replaces GlitchTip telemetry.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Optional

import httpx
import platformdirs

from local_worker._shared import current_release
from local_worker.config import load_settings
from local_worker.consent import get_consent
from local_worker.environment import detect_environment

log = logging.getLogger(__name__)

Reason = Literal['crash', 'manual']

# Hard cap mirrored from the server's WORKER_LOG_MAX_BYTES default. The
# server is authoritative; this is just a safety net so a runaway log
# doesn't blow the request body open before the server rejects it.
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _log_file_path() -> Path:
    """Return the platform-standard path to ``worker.log``.

    Returns:
        Absolute path to the primary session log; respects the
        ``WLW_LOG_DIR`` override used by the test suite.
    """
    import os

    override = os.environ.get('WLW_LOG_DIR', '').strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir('wood-league-worker', 'WoodLeague')
    )
    return base / 'worker.log'


def _host_summary() -> dict[str, Any]:
    """Snapshot the same banner info we already include in the log.

    Returns:
        Plain dict suitable for the ``host_summary`` JSON metadata field.
    """
    env = detect_environment()
    host = env.get('host', {})
    python_info = env.get('python', {})
    engines = env.get('engines', {})
    installed = sorted(name for name, info in engines.items() if info.get('path'))
    return {
        'system': host.get('system', 'unknown'),
        'machine': host.get('machine', 'unknown'),
        'python': python_info.get('version', 'unknown'),
        'engines': installed,
    }


def _build_metadata(reason: Reason) -> str:
    """Render the JSON metadata block POSTed alongside the log.

    Args:
        reason: ``"crash"`` for auto uploads, ``"manual"`` for explicit.

    Returns:
        UTF-8 JSON string ready to ship as the ``metadata`` form field.
    """
    return json.dumps({
        'reason': reason,
        'worker_version': current_release(),
        'host_summary': _host_summary(),
    })


def upload_log(reason: Reason, note: str = '') -> int:
    """Upload the current ``worker.log`` to the Wood League server.

    Args:
        reason: ``"crash"`` (auto, from the excepthook) or ``"manual"``
            (explicit, from the ``submit-log`` CLI command).
        note: Optional free-form text (truncated server-side to 4 KB).

    Returns:
        The server-issued upload id on success, or ``-1`` on any failure.
        Failures are logged locally; never raises.
    """
    settings = load_settings()
    if not settings.is_configured():
        log.warning('Cannot upload log: worker is not configured (run setup).')
        return -1

    log_path = _log_file_path()
    if not log_path.exists():
        log.warning('Cannot upload log: %s does not exist yet.', log_path)
        return -1

    try:
        size = log_path.stat().st_size
    except OSError as exc:
        log.warning('Cannot stat %s: %s', log_path, exc)
        return -1
    if size > _MAX_UPLOAD_BYTES:
        log.warning(
            'Log file %s is %d bytes — exceeds %d byte cap; not uploading.',
            log_path, size, _MAX_UPLOAD_BYTES,
        )
        return -1

    url = settings.api_url.rstrip('/') + '/api/v1/worker/logs/'
    query = '?force=true' if reason == 'crash' else ''
    try:
        with log_path.open('rb') as fh:
            files = {'log': (log_path.name, fh, 'text/plain')}
            data = {'note': note, 'metadata': _build_metadata(reason)}
            response = httpx.post(
                url + query,
                files=files,
                data=data,
                headers={'X-Api-Key': settings.api_key},
                timeout=60.0,
            )
    except httpx.RequestError as exc:
        log.warning('Log upload network error: %s', exc)
        return -1
    except OSError as exc:
        log.warning('Could not read %s: %s', log_path, exc)
        return -1

    if response.status_code != 201:
        log.warning(
            'Log upload rejected: HTTP %d %s',
            response.status_code, response.text[:200],
        )
        return -1

    try:
        body = response.json()
    except ValueError:
        return -1
    upload_id = body.get('id')
    return int(upload_id) if isinstance(upload_id, int) else -1


def _crash_excepthook(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: Optional[TracebackType],
) -> None:
    """``sys.excepthook`` replacement that offers an interactive upload.

    Args:
        exc_type: The exception class.
        exc_value: The exception instance.
        exc_traceback: The traceback object (may be ``None``).
    """
    traceback.print_exception(exc_type, exc_value, exc_traceback)
    if get_consent() is not True:
        return
    try:
        answer = input('Upload this crash log to maintainers? [Y/n] ').strip().lower()
    except EOFError:
        answer = ''
    if answer not in {'', 'y', 'yes'}:
        return
    upload_id = upload_log('crash', note=f'{exc_type.__name__}: {exc_value}'[:4096])
    if upload_id > 0:
        print(f'Uploaded crash log (id={upload_id}).', file=sys.stderr)


def install_crash_hook() -> None:
    """Install :func:`_crash_excepthook` as ``sys.excepthook``.

    Only the long-running ``run`` command currently calls this; read-only
    commands keep the default Python excepthook.
    """
    sys.excepthook = _crash_excepthook


__all__ = ['upload_log', 'install_crash_hook']
