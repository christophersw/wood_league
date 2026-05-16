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
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


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
