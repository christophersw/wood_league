"""
Title: lc0_tuning_sync.py — Persist the lc0 calibration cache to object storage
Description:
    The lc0 MinibatchSize calibration (~7.5 min `lc0 benchmark` sweep)
    is cached in lc0_tuning.json in the worker data dir, which is
    ephemeral on vast.ai — every fresh instance starts cold and pays
    the sweep. This module persists that JSON to the Railway-compatible
    bucket, keyed by a hash of its fingerprint so different
    weights/backends never clobber one another (the on-disk cache is
    single-entry). Fail-soft throughout, exactly like cache_sync.py: an
    object-storage failure must never interrupt analysis — the worker
    just recalibrates as it does today (issue #150).

    Per-network draw-rate measurements (issue #159) are stored in the same
    lc0_tuning.json file under a ``draw_rate`` section keyed by network
    name.  push_draw_rate / pull_draw_rate manage that section with the
    same fail-soft discipline.
Changelog:
    2026-05-17: Initial creation (issue #150).
    2026-05-19: Add push_draw_rate / pull_draw_rate for per-network draw-rate
                persistence in the existing lc0_tuning.json store (issue #159).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from local_worker.cache_sync import make_s3_client

log = logging.getLogger(__name__)

_KEY_PREFIX = "lc0_tuning"


def tuning_object_key(fingerprint: dict[str, str]) -> str:
    """Object key for a calibration fingerprint.

    Args:
        fingerprint: The compute_fingerprint() dict
            (gpu, lc0_version, weights, backend).

    Returns:
        ``lc0_tuning/<sha1>.json`` — deterministic and independent of
        dict key ordering, so each GPU/version/weights/backend combo
        gets its own object and none clobbers another.
    """
    canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()  # noqa: S324
    return f"{_KEY_PREFIX}/{digest}.json"


def pull_tuning(
    client: Any, bucket: str, fingerprint: dict[str, str], dest: Path
) -> bool:
    """Download this fingerprint's calibration JSON to ``dest``. Never raises.

    Args:
        client: S3 client exposing ``download_file(bucket, key, dest)``.
        bucket: Bucket name.
        fingerprint: Current host fingerprint (selects the object key).
        dest: Local path to write the calibration JSON to
            (typically ``cache_path()``).

    Returns:
        True if the object was fetched, False otherwise. A partially
        written file is removed on failure so a corrupt cache can never
        be read back.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = tuning_object_key(fingerprint)
    try:
        client.download_file(bucket, key, str(dest))
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
        log.warning(
            "lc0_tuning_sync: pull %s failed (%s); will calibrate", key, exc
        )
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def push_tuning(client: Any, bucket: str, cache_path: Path) -> None:
    """Upload the freshly written calibration JSON. Never raises.

    The object key is derived from the *embedded* fingerprint in the
    file itself, so the file always lands under the key a future
    pull_tuning() will look for.

    Args:
        client: S3 client exposing ``upload_file(src, bucket, key)``.
        bucket: Bucket name.
        cache_path: Path to the just-written lc0_tuning.json.
    """
    if not cache_path.exists():
        log.info("lc0_tuning_sync: no calibration file to push; skipping")
        return
    try:
        payload = json.loads(cache_path.read_text())
        fingerprint = payload["fingerprint"]
        key = tuning_object_key(fingerprint)
        client.upload_file(str(cache_path), bucket, key)
        log.info("lc0_tuning_sync: pushed %s", key)
    except KeyError:
        log.warning(
            "lc0_tuning_sync: cache file %s missing 'fingerprint'; cannot push",
            cache_path,
        )
    except Exception as exc:  # noqa: BLE001 — push must not break the run
        log.warning("lc0_tuning_sync: push failed (%s); ignored", exc)


def pull_draw_rate(network: str, cache_path: Path) -> "float | None":
    """Read a previously-persisted draw rate for ``network`` from the local cache.

    The draw rate lives in the ``draw_rate`` section of lc0_tuning.json,
    keyed by network name.  Returns None (fail-soft) when the file is
    absent, malformed, or the network has no entry.

    Args:
        network: Resolved network identifier (e.g. ``"BT4"``).
        cache_path: Path to the local lc0_tuning.json file.

    Returns:
        Persisted draw rate float, or None if unavailable.
    """
    try:
        payload = json.loads(cache_path.read_text())
        draw_rate_section = payload.get("draw_rate", {})
        value = draw_rate_section.get(network)
        if value is None:
            return None
        return float(value)
    except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
        log.warning(
            "lc0_tuning_sync: pull_draw_rate for net=%s failed (%s); will measure",
            network,
            exc,
        )
        return None


def push_draw_rate(network: str, draw_rate: float, cache_path: Path) -> None:
    """Persist ``draw_rate`` for ``network`` in the local lc0_tuning.json.

    Reads the existing file (if any), merges the new value into the
    ``draw_rate`` section, and writes the updated payload atomically.
    Creates the file from scratch when it does not yet exist.  Never
    raises — a write failure is logged and silently ignored so analysis
    is never interrupted.

    Args:
        network: Resolved network identifier (e.g. ``"BT4"``).
        draw_rate: Measured draw fraction to persist.
        cache_path: Path to the local lc0_tuning.json file.
    """
    try:
        if cache_path.exists():
            payload: dict = json.loads(cache_path.read_text())
        else:
            payload = {}
        draw_rate_section: dict = payload.setdefault("draw_rate", {})
        draw_rate_section[network] = draw_rate
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload))
        log.info(
            "lc0_tuning_sync: persisted draw_rate=%.4f for net=%s",
            draw_rate,
            network,
        )
    except Exception as exc:  # noqa: BLE001 — never interrupt analysis
        log.warning(
            "lc0_tuning_sync: push_draw_rate for net=%s failed (%s); ignored",
            network,
            exc,
        )


def push_after_calibrate(cache_path: Path) -> None:
    """Env-gated, fail-soft auto-push hook for get_tuned_opts(on_calibrated=).

    Builds an S3 client from env and pushes. A no-op (logged) when no
    bucket is configured (e.g. local dev / non-vast), so wiring this
    into the analysis path is safe everywhere.

    Args:
        cache_path: Path to the just-written lc0_tuning.json.
    """
    if not os.environ.get("RAILWAY_BUCKET_NAME"):
        log.info("lc0_tuning_sync: no bucket configured; skip calibration push")
        return
    try:
        client, bucket = make_s3_client()
    except Exception as exc:  # noqa: BLE001 — never break analysis
        log.warning("lc0_tuning_sync: S3 client init failed (%s); ignored", exc)
        return
    push_tuning(client, bucket, cache_path)
