"""
Title: Analysis Services Package
Description: Re-exports status-query functions from analysis.services_queries so that
    ``from . import services`` in views.py resolves queue_totals, queue_by_engine,
    runpod_health, worker_heartbeats, and recent_jobs via the package root.
    Also re-exports enqueue_analysis_job — the single source of truth for
    dedup-safe AnalysisJob creation.
Changelog:
    2026-05-08 C. Webster — Initial: add re-exports to fix mypy attr-defined errors.
    2026-05-10 C. Webster — A3: add enqueue_analysis_job re-export.
"""

from analysis.services.enqueue import enqueue_analysis_job
from analysis.services_queries import (
    queue_totals,
    queue_by_engine,
    runpod_health,
    worker_heartbeats,
    recent_jobs,
)

__all__ = [
    "enqueue_analysis_job",
    "queue_totals",
    "queue_by_engine",
    "runpod_health",
    "worker_heartbeats",
    "recent_jobs",
]
