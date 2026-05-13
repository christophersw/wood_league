"""
Title: log_storage.py — Object-storage helpers for worker log uploads
Description:
    Thin wrapper around boto3's S3 client configured for the Railway
    object-storage bucket. Centralises the ``endpoint_url`` plumbing so
    views, admin actions, and the retention command share one code path.

Changelog:
    2026-05-13 (#52): Initial creation. Backs WorkerLogUpload flows.
"""
from __future__ import annotations

from typing import IO, Any, Optional

import boto3
from botocore.client import Config
from django.conf import settings


def _client() -> Any:
    """Build a boto3 S3 client pointed at the configured Railway bucket.

    Returns:
        A fresh ``boto3.client('s3', ...)`` instance. Each call creates a
        new client so threads do not share a single mutable session.
    """
    return boto3.client(
        's3',
        endpoint_url=settings.WORKER_LOG_S3_ENDPOINT or None,
        region_name=settings.WORKER_LOG_S3_REGION,
        aws_access_key_id=settings.WORKER_LOG_S3_ACCESS_KEY or None,
        aws_secret_access_key=settings.WORKER_LOG_S3_SECRET_KEY or None,
        config=Config(signature_version='s3v4'),
    )


def upload_stream(file_obj: IO[bytes], bucket_key: str) -> None:
    """Stream a file-like object to the configured bucket.

    Args:
        file_obj: Binary, readable file-like object positioned at start.
        bucket_key: Object key inside the bucket.
    """
    _client().upload_fileobj(
        Fileobj=file_obj,
        Bucket=settings.WORKER_LOG_BUCKET,
        Key=bucket_key,
    )


def presigned_get_url(bucket_key: str, ttl_seconds: Optional[int] = None) -> str:
    """Mint a short-lived presigned GET URL for ``bucket_key``.

    Args:
        bucket_key: Object key inside the bucket.
        ttl_seconds: Lifetime of the presigned URL. Defaults to the
            project-wide ``WORKER_LOG_PRESIGN_TTL_SECONDS`` setting.

    Returns:
        Absolute URL the browser can hit directly to download the object.
    """
    expires = ttl_seconds if ttl_seconds is not None else settings.WORKER_LOG_PRESIGN_TTL_SECONDS
    return _client().generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': settings.WORKER_LOG_BUCKET, 'Key': bucket_key},
        ExpiresIn=expires,
    )


def fetch_object(bucket_key: str) -> bytes:
    """Read the entire object body into memory.

    Used by the admin "bulk download zip" action. Worker logs are at most
    ``WORKER_LOG_MAX_BYTES``, so a few of them at once fit in memory.

    Args:
        bucket_key: Object key inside the bucket.

    Returns:
        Raw bytes of the object body.
    """
    response = _client().get_object(Bucket=settings.WORKER_LOG_BUCKET, Key=bucket_key)
    return response['Body'].read()


def delete_object(bucket_key: str) -> None:
    """Best-effort deletion of a single object from the bucket.

    Args:
        bucket_key: Object key inside the bucket.
    """
    _client().delete_object(Bucket=settings.WORKER_LOG_BUCKET, Key=bucket_key)


__all__ = [
    'upload_stream',
    'presigned_get_url',
    'fetch_object',
    'delete_object',
]
