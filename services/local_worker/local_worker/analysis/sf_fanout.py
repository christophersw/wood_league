"""
Title: sf_fanout.py — Pure host→Stockfish fan-out sizing
Description:
    Given the host's logical CPU count, available RAM, and the optional
    per-engine WLW_MAX_JOBS cap, compute how many concurrent Stockfish
    worker processes to run, the per-process Threads/Hash, and how to
    partition the job cap across them. Pure (no I/O) so it is fully
    unit-testable; the host probing lives in the plan-sf-fanout command.

    Heuristic (see 2026-05-16 spec): Stockfish scales ~linearly to ~4-8
    threads, so many modest workers beat few fat ones for bulk
    throughput. CPU and RAM are both budgeted; RAM is allowed to be the
    binding constraint. A safety cap bounds eval-cache concurrent
    writers.
Changelog:
    2026-05-16: Initial creation (#130).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SF_THREADS_DEFAULT = 4
SF_HASH_MB_CAP = 512
SF_MAX_WORKERS = 16
# lc0 (3) + OS (1) logical CPUs held back from Stockfish.
CPU_RESERVE = 4
# lc0 (6144 MB) + OS (1024 MB) RAM held back from Stockfish.
RAM_RESERVE_MB = 7168
# Per-worker RAM footprint: Hash cap (512) + base process (256).
SF_SLOT_MB = SF_HASH_MB_CAP + 256


@dataclass(frozen=True)
class FanoutPlan:
    """Resolved Stockfish fan-out for this host.

    Attributes:
        workers: Number of concurrent Stockfish worker processes.
        threads: Stockfish ``Threads`` per worker.
        hash_mb: Stockfish ``Hash`` (MB) per worker.
        job_split: Per-worker ``--max-jobs`` values; empty list means
            unbounded (no WLW_MAX_JOBS cap). ``sum`` == the cap;
            ``len`` == workers.
    """

    workers: int
    threads: int
    hash_mb: int
    job_split: list[int]


def effective_vcpu(
    *,
    cpu_count: Optional[int],
    affinity: Optional[int],
    cgroup_cpus: Optional[float],
) -> int:
    """Smallest credible logical-CPU count for fan-out sizing.

    On a sliced container ``os.cpu_count()`` reports the *physical host*,
    not the rented allocation, which over-subscribes Stockfish (#134).
    The process CPU affinity and the cgroup CPU quota both reflect the
    real slice, so the binding constraint is the min of whichever
    signals are present. Absent/None or non-positive signals are
    ignored; the result is always >= 1.

    Args:
        cpu_count: ``os.cpu_count()`` (host view), or None.
        affinity: ``len(os.sched_getaffinity(0))``, or None where the
            platform lacks it (macOS/Windows).
        cgroup_cpus: cgroup CPU quota in whole-CPU equivalents
            (quota/period), or None when unset/unlimited.

    Returns:
        Clamped logical CPU count, >= 1.
    """
    signals = (cpu_count, affinity, cgroup_cpus)
    candidates = [max(1, int(s)) for s in signals if s and s > 0]
    return min(candidates) if candidates else 1


def _split_jobs(total: int, workers: int) -> list[int]:
    """Partition ``total`` jobs across ``workers`` as evenly as possible.

    Remainder goes to the first workers. ``len`` == workers, ``sum`` ==
    total.
    """
    base, rem = divmod(total, workers)
    return [base + (1 if i < rem else 0) for i in range(workers)]


def plan_fanout(
    *,
    vcpu: Optional[int],
    avail_ram_mb: int,
    max_jobs: Optional[int],
) -> FanoutPlan:
    """Compute the Stockfish fan-out for the current host.

    Args:
        vcpu: Host logical CPU count (``os.cpu_count()``); None → treat
            as 1.
        avail_ram_mb: Currently-available RAM in MB.
        max_jobs: Per-engine WLW_MAX_JOBS cap, or None for unbounded.

    Returns:
        A :class:`FanoutPlan`.
    """
    cpus = vcpu if (vcpu and vcpu > 0) else 1
    cpu_workers = max(1, max(1, cpus - CPU_RESERVE) // SF_THREADS_DEFAULT)
    ram_budget = max(0, avail_ram_mb - RAM_RESERVE_MB)
    ram_workers = max(1, ram_budget // SF_SLOT_MB)
    workers = min(cpu_workers, ram_workers, SF_MAX_WORKERS)

    if max_jobs and max_jobs >= 1:
        workers = min(workers, max_jobs)
        job_split = _split_jobs(max_jobs, workers)
    else:
        job_split = []

    return FanoutPlan(workers, SF_THREADS_DEFAULT, SF_HASH_MB_CAP, job_split)
