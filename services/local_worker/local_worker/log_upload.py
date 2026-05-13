"""
Title: log_upload.py — Worker session-log uploader
Description:
    Reads the current ``worker.log`` and POSTs it to the Wood League
    server's ``/api/v1/worker/logs/`` endpoint as a multipart upload.
    Used by both the explicit ``submit-log`` CLI command and the
    excepthook in :mod:`local_worker._crash_hook`. All failures are
    caught locally: a network error never propagates out and never
    crashes the running worker.

Changelog:
    2026-05-13 (#52): Initial creation. Replaces GlitchTip telemetry.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from local_worker._crash_hook import install_crash_hook
from local_worker._log_upload_meta import (
    Reason,
    build_metadata,
    log_file_path,
    preflight,
)
from local_worker.config import load_settings

log = logging.getLogger(__name__)


def _parse_response(response: Any) -> int:
    """Extract the new upload's id from a successful response.

    Args:
        response: ``httpx.Response`` from the server.

    Returns:
        Numeric id on success, or ``-1`` on any non-201 / parse failure.
    """
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

    log_path = log_file_path()
    if preflight(log_path) < 0:
        return -1

    query = '?force=true' if reason == 'crash' else ''
    url = settings.api_url.rstrip('/') + '/api/v1/worker/logs/' + query
    try:
        with log_path.open('rb') as fh:
            response = httpx.post(
                url,
                files={'log': (log_path.name, fh, 'text/plain')},
                data={'note': note, 'metadata': build_metadata(reason)},
                headers={'X-Api-Key': settings.api_key},
                timeout=60.0,
            )
    except (httpx.RequestError, OSError) as exc:
        log.warning('Log upload network/IO error: %s', exc)
        return -1

    return _parse_response(response)


__all__ = ['upload_log', 'install_crash_hook']
