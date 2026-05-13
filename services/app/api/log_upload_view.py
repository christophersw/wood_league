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

import logging
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
from api.log_upload_helpers import build_bucket_key, parse_metadata, too_soon
from api.models import WorkerLogUpload

log = logging.getLogger(__name__)

_REASON_CRASH = WorkerLogUpload.REASON_CRASH
_REASON_MANUAL = WorkerLogUpload.REASON_MANUAL
_NOTE_MAX_BYTES = 4 * 1024


def _validate_upload(request: Request) -> Any:
    """Return the file part of the multipart request, or a 4xx response.

    Args:
        request: Incoming DRF request.

    Returns:
        The uploaded file object on success, or a :class:`Response`
        carrying the appropriate ``400``/``413``/``503`` status when the
        request cannot be served.
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
    return uploaded


def _normalize_reason(metadata: dict[str, Any]) -> str:
    """Return a valid reason string from the metadata block.

    Args:
        metadata: Parsed metadata dict.

    Returns:
        Either ``"crash"`` or ``"manual"``; falls back to ``"manual"``.
    """
    reason = metadata.get('reason', _REASON_MANUAL)
    return reason if reason in {_REASON_CRASH, _REASON_MANUAL} else _REASON_MANUAL


def _is_force(request: Request) -> bool:
    """Return ``True`` when the request opts into the rate-limit bypass.

    Args:
        request: Incoming DRF request.

    Returns:
        ``True`` if ``?force=true|1|yes`` is set.
    """
    return str(request.query_params.get('force', '')).lower() in {'1', 'true', 'yes'}


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
        uploaded = _validate_upload(request)
        if isinstance(uploaded, Response):
            return uploaded

        note = (request.data.get('note') or '')[:_NOTE_MAX_BYTES]
        metadata = parse_metadata(request.data.get('metadata') or '')
        reason = _normalize_reason(metadata)
        force = _is_force(request)
        worker = request.auth
        if too_soon(worker, force):
            return Response(
                {'error': 'too many uploads — try again shortly'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        bucket_key = build_bucket_key(worker.prefix)
        try:
            upload_stream(uploaded.file, bucket_key)
        except Exception as exc:  # noqa: BLE001 - boto3 raises many subclasses
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
