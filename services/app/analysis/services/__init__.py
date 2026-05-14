"""
Title: Analysis Services Package
Description: Re-exports status-query functions from analysis.services_queries so that
    ``from . import services`` in views.py resolves queue_totals, queue_by_engine,
    worker_heartbeats, and recent_jobs via the package root.
    Also re-exports enqueue_analysis_job — the single source of truth for
    dedup-safe AnalysisJob creation.
Changelog:
    2026-05-14 (#106): Drop runpod_health re-export — probe removed.
    2026-05-08 C. Webster — Initial: add re-exports to fix mypy attr-defined errors.
    2026-05-10 C. Webster — A3: add enqueue_analysis_job re-export.
    2026-05-10 C. Webster — A4: add submit_job_to_runpod re-export.
    2026-05-14 C. Webster — Issue #101 Phase A: drop submit_job_to_runpod
        re-export now that pod workers pull jobs directly.
"""

from analysis.services.enqueue import enqueue_analysis_job
from analysis.services_queries import (
    queue_totals,
    queue_by_engine,
    worker_heartbeats,
    recent_jobs,
)

__all__ = [
    "enqueue_analysis_job",
    "queue_totals",
    "queue_by_engine",
    "worker_heartbeats",
    "recent_jobs",
]
