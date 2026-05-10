"""
Title: Analysis Services Package
Description: Re-exports status-query functions from analysis.services_queries so that
    ``from . import services`` in views.py resolves queue_totals, queue_by_engine,
    runpod_health, worker_heartbeats, and recent_jobs via the package root.
    Also re-exports enqueue_analysis_job — the single source of truth for
    dedup-safe AnalysisJob creation — and submit_job_to_runpod for dispatching
    pending jobs to RunPod serverless endpoints.
Changelog:
    2026-05-08 C. Webster — Initial: add re-exports to fix mypy attr-defined errors.
    2026-05-10 C. Webster — A3: add enqueue_analysis_job re-export.
    2026-05-10 C. Webster — A4: add submit_job_to_runpod re-export.
"""

from analysis.services.enqueue import enqueue_analysis_job
from analysis.services.runpod_dispatch import submit_job_to_runpod
from analysis.services_queries import (
    queue_totals,
    queue_by_engine,
    runpod_health,
    worker_heartbeats,
    recent_jobs,
)

__all__ = [
    "enqueue_analysis_job",
    "submit_job_to_runpod",
    "queue_totals",
    "queue_by_engine",
    "runpod_health",
    "worker_heartbeats",
    "recent_jobs",
]
