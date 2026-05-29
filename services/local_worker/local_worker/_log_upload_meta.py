"""
Title: _log_upload_meta.py — Metadata + path helpers for log_upload
Description:
    Pure helpers used by :mod:`local_worker.log_upload`. Split out to
    keep each module under the project Halstead-effort gate.

Changelog:
    2026-05-13 (#52): Initial creation.
    2026-05-14 (#85): Added ``session_end`` reason for the graceful-exit
        auto-upload hook in ``commands/run.py``.
    2026-05-28 (#223): Glob ``lc0*.log`` so every per-GPU lc0 log
        uploads; keep excluding ``*.diagnostics.log``.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal

import platformdirs

from local_worker._shared import current_release
from local_worker.environment import detect_environment

log = logging.getLogger(__name__)

Reason = Literal['crash', 'manual', 'session_end']
SESSION_END: Reason = 'session_end'

# Mirror of the server's WORKER_LOG_MAX_BYTES default.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def log_file_path() -> Path:
    """Return the platform-standard path to ``worker.log``.

    Returns:
        Absolute path. Respects ``WLW_LOG_DIR`` for the test suite.
    """
    override = os.environ.get('WLW_LOG_DIR', '').strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir('wood-league-worker', 'WoodLeague')
    )
    return base / 'worker.log'


def host_summary() -> dict[str, Any]:
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


def build_metadata(reason: Reason) -> str:
    """Render the JSON metadata block POSTed alongside the log.

    Args:
        reason: ``"crash"`` for auto uploads, ``"manual"`` for explicit.

    Returns:
        UTF-8 JSON string ready to ship as the ``metadata`` form field.
    """
    return json.dumps({
        'reason': reason,
        'worker_version': current_release(),
        'host_summary': host_summary(),
    })


def preflight(log_path: Path) -> int:
    """Validate the log file exists and is within size limits.

    Args:
        log_path: Path to ``worker.log``.

    Returns:
        File size in bytes when valid; ``-1`` when the file is missing,
        unreadable, or larger than the project upload cap.
    """
    if not log_path.exists():
        log.warning('Cannot upload log: %s does not exist yet.', log_path)
        return -1
    try:
        size = log_path.stat().st_size
    except OSError as exc:
        log.warning('Cannot stat %s: %s', log_path, exc)
        return -1
    if size > MAX_UPLOAD_BYTES:
        log.warning(
            'Log file %s exceeds %d byte cap; not uploading.',
            log_path, MAX_UPLOAD_BYTES,
        )
        return -1
    return size


def resolve_engine_log_paths() -> list[Path]:
    """Return the log files to upload for this session.

    Under the vast fan-out a session writes per-engine logs rather than
    a single ``worker.log``. With multiple GPUs there is one lc0 log per
    GPU (``lc0-gpu0.log``, ``lc0-gpu1.log``, …) plus the shared
    ``stockfish.log`` (#223), so lc0 logs are matched by glob. The
    per-engine ``*.diagnostics.log`` companions are deliberately not
    uploaded. Returns every present, non-empty engine log in the log
    directory; falls back to the single configured log (validated via
    :func:`preflight`) for non-vast callers.

    Returns:
        Ordered list of existing log paths. Empty when nothing is
        uploadable.
    """
    base = log_file_path()  # <log_dir>/worker.log
    log_dir = base.parent
    candidates = sorted(log_dir.glob('lc0*.log'))
    candidates += [log_dir / 'stockfish.log', log_dir / 'worker.log']
    present = [
        p for p in candidates
        if not p.name.endswith('.diagnostics.log')
        and p.exists() and p.stat().st_size > 0
    ]
    if present:
        return present
    return [base] if preflight(base) >= 0 else []


__all__ = [
    'Reason', 'SESSION_END',
    'log_file_path', 'host_summary', 'build_metadata', 'preflight',
    'resolve_engine_log_paths',
]
