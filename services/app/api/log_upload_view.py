"""
Title: log_upload_view.py — Worker log upload endpoint
Description:
    Implements ``POST /api/v1/worker/logs/`` for analysis workers to push
    their session log to the maintainer-accessible object-storage bucket.
    Authenticates with the existing ``WorkerAPIKeyAuthentication`` and
    persists a :class:`WorkerLogUpload` row for each successful upload.

Changelog:
    2026-05-13 (#52): Initial creation. Replaces GlitchTip telemetry.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from hashlib import sha256
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import HasWorkerAPIKey
from api.log_storage import upload_stream
from api.models import WorkerLogUpload

log = logging.getLogger(__name__)

_REASON_CRASH = WorkerLogUpload.REASON_CRASH
_REASON_MANUAL = WorkerLogUpload.REASON_MANUAL
_NOTE_MAX_BYTES = 4 * 1024


def _hash_worker_id(prefix: str) -> str:
    """Return a 12-char hex prefix of the SHA-256 of ``prefix``.

    Args:
        prefix: Non-secret 8-char API-key prefix from the authenticated key.

    Returns:
        Short hex string used as the per-worker bucket directory.
    """
    if not prefix:
        return 'anonymous'
    return sha256(prefix.encode('utf-8', errors='ignore')).hexdigest()[:12]


def _parse_metadata(raw: str) -> dict[str, Any]:
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


def _too_soon(worker: Any, force: bool) -> bool:
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


def _build_bucket_key(worker_prefix: str) -> str:
    """Render the bucket key under which the worker's log will be stored.

    Args:
        worker_prefix: Non-secret API-key prefix of the authenticated worker.

    Returns:
        ``<hash>/<iso-timestamp>.log`` path inside the bucket.
    """
    stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
    return f'{_hash_worker_id(worker_prefix)}/{stamp}.log'


class WorkerLogUploadView(APIView):
    """Accept a session log upload from an authenticated worker."""

    permission_classes: list[type] = [HasWorkerAPIKey]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        """Handle one multipart upload, streaming the body to the bucket.

        Args:
            request: DRF request carrying ``log`` (file), ``note`` (str),
                and ``metadata`` (JSON str) parts.

        Returns:
            ``201`` with the new row id + bucket key on success; ``400``
            for missing fields, ``413`` when too large, ``429`` when rate
            limited, or ``503`` when the bucket is not configured.
        """
        if not settings.WORKER_LOG_BUCKET:
            return Response(
                {'error': 'log upload not configured on this server'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        uploaded = request.FILES.get('log')
        if uploaded is None:
            return Response(
                {'error': 'missing "log" file part'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if uploaded.size is not None and uploaded.size > settings.WORKER_LOG_MAX_BYTES:
            return Response(
                {'error': 'log file exceeds maximum size'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        note = (request.data.get('note') or '')[:_NOTE_MAX_BYTES]
        metadata = _parse_metadata(request.data.get('metadata') or '')

        reason = metadata.get('reason', _REASON_MANUAL)
        if reason not in {_REASON_CRASH, _REASON_MANUAL}:
            reason = _REASON_MANUAL

        force = str(request.query_params.get('force', '')).lower() in {'1', 'true', 'yes'}
        worker = request.auth
        if _too_soon(worker, force):
            return Response(
                {'error': 'too many uploads — try again shortly'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        bucket_key = _build_bucket_key(worker.prefix)
        try:
            upload_stream(uploaded.file, bucket_key)
        except Exception as exc:  # noqa: BLE001 - boto3 raises ClientError, BotoCoreError, etc.
            log.exception('worker log upload to bucket failed: %s', exc)
            return Response(
                {'error': 'bucket upload failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        host_summary = metadata.get('host_summary', {})
        if not isinstance(host_summary, dict):
            host_summary = {}

        with transaction.atomic():
            row = WorkerLogUpload.objects.create(
                worker=worker,
                bucket_key=bucket_key,
                size_bytes=uploaded.size or 0,
                note=note,
                reason=reason,
                worker_version=str(metadata.get('worker_version', ''))[:32],
                host_summary=host_summary,
            )
            worker.last_used_at = timezone.now()
            worker.save(update_fields=['last_used_at'])

        return Response(
            {'id': row.id, 'bucket_key': bucket_key},
            status=status.HTTP_201_CREATED,
        )


__all__ = ['WorkerLogUploadView']
