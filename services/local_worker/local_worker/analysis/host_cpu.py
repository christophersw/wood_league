"""
Title: host_cpu.py — Real-slice host CPU probing for fan-out sizing
Description:
    The I/O side of Stockfish fan-out CPU sizing, split out of
    plan_sf_fanout_cmd so each module stays small and the probes are
    unit-testable without the CLI. ``os.cpu_count()`` reports the
    *physical host* inside a sliced vast container, which over-subscribes
    Stockfish (#134); the process CPU affinity and the cgroup CPU quota
    reflect the real rented allocation. The pure min() math lives in
    ``sf_fanout.effective_vcpu``; this module only gathers the signals.
Changelog:
    2026-05-17: Initial creation (#134) — extracted from
        plan_sf_fanout_cmd.
"""
from __future__ import annotations

import os
from pathlib import Path

from local_worker.analysis.sf_fanout import effective_vcpu

_CGROUP_V2_MAX = Path("/sys/fs/cgroup/cpu.max")
_CGROUP_V1_QUOTA = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
_CGROUP_V1_PERIOD = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")


def _ratio(quota: float, period: float) -> float | None:
    """quota/period as whole-CPU equivalents, or None when not a
    positive bounded quota."""
    if quota > 0 and period > 0:
        return quota / period
    return None


def _cgroup_cpus() -> float | None:
    """cgroup CPU quota in whole-CPU equivalents.

    Tries cgroup v2 (``cpu.max``: ``"<quota> <period>"`` or ``"max"``)
    then v1 (``cpu.cfs_quota_us`` / ``cpu.cfs_period_us``). Returns None
    when unset, unlimited (``max`` / quota ``-1``), or unreadable.
    """
    try:
        parts = _CGROUP_V2_MAX.read_text().split()
        if parts and parts[0] != "max":
            period = float(parts[1]) if len(parts) > 1 else 100000.0
            hit = _ratio(float(parts[0]), period)
            if hit is not None:
                return hit
    except (OSError, ValueError):
        pass
    try:
        hit = _ratio(
            float(_CGROUP_V1_QUOTA.read_text()),
            float(_CGROUP_V1_PERIOD.read_text()),
        )
        if hit is not None:
            return hit
    except (OSError, ValueError):
        pass
    return None


def _affinity_cpus() -> int | None:
    """Logical CPUs the process may run on, or None where the platform
    has no ``sched_getaffinity`` (macOS/Windows)."""
    getaff = getattr(os, "sched_getaffinity", None)
    if getaff is None:
        return None
    try:
        return len(getaff(0))
    except OSError:
        return None


def host_vcpu() -> int:
    """Effective logical CPU count for fan-out sizing.

    Clamps the host ``os.cpu_count()`` down to the rented slice via CPU
    affinity and the cgroup quota — sliced vast containers report the
    physical host and would otherwise over-subscribe Stockfish (#134).
    """
    return effective_vcpu(
        cpu_count=os.cpu_count(),
        affinity=_affinity_cpus(),
        cgroup_cpus=_cgroup_cpus(),
    )
