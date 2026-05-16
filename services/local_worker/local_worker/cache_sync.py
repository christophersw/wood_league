"""
Title: cache_sync.py — vast.ai eval-cache boot pull / checkpoint upload
Description:
    Pulls the canonical engine eval cache from S3-compatible object
    storage at instance boot (fail-soft) and uploads WAL-safe snapshots
    of this instance's cache as per-campaign/per-instance deltas. No
    host-scoped volume is involved; the canonical compounds across
    campaigns via the offline merge job (cache_merge.py).
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
from __future__ import annotations

import logging
import os
import sqlite3

import boto3
from pathlib import Path

log = logging.getLogger(__name__)

CANONICAL_KEY = "eval_cache/canonical.sqlite"


def checkpoint_key(campaign_id: str, instance_id: str) -> str:
    """Return the per-campaign/per-instance object key for a cache delta.

    Args:
        campaign_id: Logical campaign identifier (``WL_CAMPAIGN_ID``).
        instance_id: Stable per-instance identifier (``WL_INSTANCE_ID``).

    Returns:
        Object key, e.g. ``eval_cache/checkpoints/<campaign>/<instance>.sqlite``.
    """
    return f"eval_cache/checkpoints/{campaign_id}/{instance_id}.sqlite"


def make_s3_client() -> tuple[object, str]:
    """Build an S3 client for the Railway-compatible bucket from env.

    Mirrors ``services/app/api/log_storage.py`` but reads ``os.environ``
    directly (the worker is a standalone package and cannot import the
    Django app). Env vars: ``RAILWAY_BUCKET_NAME``, ``ENDPOINT``,
    ``REGION`` (default ``us-east-1``), ``ACCESS_KEY_ID``,
    ``SECRET_ACCESS_KEY``.

    Returns:
        ``(client, bucket_name)``.
    """
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT") or None,
        region_name=os.environ.get("REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("SECRET_ACCESS_KEY"),
    )
    return client, os.environ.get("RAILWAY_BUCKET_NAME", "")


def snapshot_db(src: Path, dst: Path) -> None:
    """Write a consistent copy of a (possibly WAL-active) SQLite DB.

    Uses ``VACUUM INTO`` so a snapshot can be taken while worker
    processes hold the source open in WAL mode. ``VACUUM INTO`` reads a
    consistent transaction and writes a fully-checkpointed standalone DB.

    Args:
        src: Path to the live eval-cache SQLite file.
        dst: Destination path for the snapshot (overwritten if present).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    conn = sqlite3.connect(str(src))
    try:
        conn.execute("VACUUM INTO ?", (str(dst),))
    finally:
        conn.close()
