"""
Title: log_upload_helpers.py — Helpers for the worker log upload view
Description:
    Pure helpers used by :mod:`api.log_upload_view`. Split out of the
    view module so each file fits comfortably under the Halstead-effort
    quality gate.

Changelog:
    2026-05-13 (#52): Initial creation.
"""
from __future__ import annotations

import json
from datetime import timedelta
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.utils import timezone

from api.models import WorkerLogUpload


def hash_worker_id(prefix: str) -> str:
    """Return a 12-char hex prefix of the SHA-256 of ``prefix``.

    Args:
        prefix: Non-secret 8-char API-key prefix from the authenticated key.

    Returns:
        Short hex string used as the per-worker bucket directory.
    """
    if not prefix:
        return 'anonymous'
    return sha256(prefix.encode('utf-8', errors='ignore')).hexdigest()[:12]


def parse_metadata(raw: str) -> dict[str, Any]:
    """Parse the ``metadata`` form field; return ``{}`` on any failure.

    Args:
        raw: UTF-8 string from the multipart ``metadata`` part.

    Returns:
        Parsed dict, or an empty dict if the value is missing/invalid.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def too_soon(worker: Any, force: bool) -> bool:
    """Return ``True`` if the worker uploaded within the cooldown window.

    Args:
        worker: Authenticated ``WorkerAPIKey`` instance.
        force: When True, bypass the cooldown unconditionally.

    Returns:
        ``True`` when the request should be rejected for rate limiting.
    """
    if force:
        return False
    cooldown = settings.WORKER_LOG_RATE_LIMIT_SECONDS
    if cooldown <= 0:
        return False
    threshold = timezone.now() - timedelta(seconds=cooldown)
    return WorkerLogUpload.objects.filter(
        worker=worker, uploaded_at__gte=threshold
    ).exists()


def build_bucket_key(worker_prefix: str) -> str:
    """Render the bucket key under which the worker's log will be stored.

    Args:
        worker_prefix: Non-secret API-key prefix of the authenticated worker.

    Returns:
        ``<hash>/<iso-timestamp>.log`` path inside the bucket.
    """
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    return f'{hash_worker_id(worker_prefix)}/{stamp}.log'


__all__ = ['hash_worker_id', 'parse_metadata', 'too_soon', 'build_bucket_key']
