"""
Title: plan_sf_fanout_cmd.py — `plan-sf-fanout` CLI command
Description:
    Detects host vCPU + available RAM, reads the optional WLW_MAX_JOBS
    cap, runs the pure sf_fanout planner, and prints shell-eval-able
    env lines for onstart.sh:

        SF_WORKERS=<n>
        SF_THREADS=<t>
        SF_HASH_MB=<mb>
        SF_JOB_SPLIT='<space-separated per-worker caps, empty=unbounded>'

Changelog:
    2026-05-16: Initial creation (#130).
    2026-05-17: Clamp host CPU to the real slice via CPU affinity +
        cgroup quota — os.cpu_count() over-reports on sliced vast
        containers and over-subscribed Stockfish (#134).
    2026-05-28: Read WL_GPU_COUNT (set by onstart.sh) and pass it to the
        planner so reserves scale per GPU (#223).
"""
from __future__ import annotations

import os

import typer

from local_worker.analysis.host_cpu import host_vcpu as _host_vcpu
from local_worker.analysis.sf_fanout import plan_fanout


def _host_avail_ram_mb() -> int:
    """Currently-available RAM in MB; conservative 1024 if psutil absent."""
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return 1024
    return int(psutil.virtual_memory().available // (1024 * 1024))


def _read_max_jobs() -> int | None:
    raw = os.environ.get("WLW_MAX_JOBS", "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 1 else None


def _read_gpu_count() -> int:
    """GPU count from ``WL_GPU_COUNT`` (set by onstart.sh); floor 1.

    onstart.sh detects the GPU count via ``nvidia-smi`` and exports it so
    the fan-out reserves CPU/RAM for one lc0 process per GPU (#223). A
    missing, non-numeric, or non-positive value falls back to a single
    GPU.
    """
    raw = os.environ.get("WL_GPU_COUNT", "").strip()
    try:
        parsed = int(raw)
    except ValueError:
        return 1
    return parsed if parsed >= 1 else 1


def plan_sf_fanout() -> None:
    """Print the resolved Stockfish fan-out as eval-able shell env."""
    plan = plan_fanout(
        vcpu=_host_vcpu(),
        avail_ram_mb=_host_avail_ram_mb(),
        max_jobs=_read_max_jobs(),
        gpus=_read_gpu_count(),
    )
    split = " ".join(str(n) for n in plan.job_split)
    typer.echo(f"SF_WORKERS={plan.workers}")
    typer.echo(f"SF_THREADS={plan.threads}")
    typer.echo(f"SF_HASH_MB={plan.hash_mb}")
    typer.echo(f"SF_JOB_SPLIT='{split}'")
