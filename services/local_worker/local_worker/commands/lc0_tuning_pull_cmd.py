"""
Title: lc0_tuning_pull_cmd.py — `lc0-tuning-pull` CLI command
Description:
    Invoked from onstart.sh at instance boot (mirrors `plan-sf-fanout`).
    Reconstructs the lc0 calibration fingerprint from the worker's
    image env (exactly as lc0.py's get_tuned_opts call does:
    gpu/lc0_version empty, weights basename, backend from env), then
    fail-soft pulls that fingerprint's cached calibration from the
    bucket into cache_path(). A hit means the next analysis run skips
    the ~7.5-minute MinibatchSize sweep entirely (issue #150).
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
from __future__ import annotations

import os
from pathlib import Path

import typer

from local_worker.analysis.lc0_tuning import cache_path, compute_fingerprint
from local_worker.cache_sync import make_s3_client
from local_worker.lc0_tuning_sync import pull_tuning


def _fingerprint_from_env() -> dict:
    """Build the calibration fingerprint from image env vars.

    Mirrors local_worker.analysis.lc0._merge_tuned_opts: gpu_name and
    lc0_version are empty (that is how get_tuned_opts is called), so the
    fingerprint depends only on the weights basename and backend.

    Returns:
        The compute_fingerprint() dict for the current image config.
    """
    return compute_fingerprint(
        "",  # gpu_name — empty, mirrors lc0.py
        "",  # lc0_version — empty, mirrors lc0.py
        os.environ.get("WLW_LC0_WEIGHTS_PATH", ""),
        os.environ.get("WLW_LC0_BACKEND", ""),
    )


def lc0_tuning_pull() -> None:
    """Fail-soft boot pull of this fingerprint's calibration cache.

    Reads the bucket from RAILWAY_BUCKET_NAME and the lc0 config from
    WLW_LC0_WEIGHTS_PATH / WLW_LC0_BACKEND. Prints a single diagnostic
    line to stdout. Never raises; a miss or any error leaves
    calibration to the first analysis run.

    Returns:
        None. Side effect: may write cache_path() and prints status.
    """
    if not os.environ.get("RAILWAY_BUCKET_NAME"):
        typer.echo("lc0-tuning-pull: no bucket configured; skip")
        return
    fingerprint = _fingerprint_from_env()
    # Informational only — proceed anyway; the pull will miss gracefully.
    if not fingerprint.get("weights") and not fingerprint.get("backend"):
        typer.echo(
            "lc0-tuning-pull: WLW_LC0_WEIGHTS_PATH/WLW_LC0_BACKEND unset; "
            "fingerprint is empty, expect miss"
        )
    try:
        client, bucket = make_s3_client()
    except Exception as exc:  # noqa: BLE001 — boot must not fail
        typer.echo(f"lc0-tuning-pull: S3 init failed ({exc}); will calibrate")
        return
    dest: Path = cache_path()
    ok = pull_tuning(client, bucket, fingerprint, dest)
    typer.echo(
        "lc0-tuning-pull: cache hit (sweep skipped)"
        if ok
        else "lc0-tuning-pull: miss; worker will calibrate once"
    )
