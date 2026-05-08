"""Analysis status data queries."""

from __future__ import annotations

from django.db.models import Count

from .models import AnalysisJob, WorkerHeartbeat


def queue_totals() -> dict[str, int]:
    """Retrieve count of analysis jobs grouped by status."""
    rows = (
        AnalysisJob.objects
        .values("status")
        .annotate(n=Count("id"))
    )
    return {r["status"]: r["n"] for r in rows}


def queue_by_engine() -> list[dict]:
    """Retrieve analysis job counts grouped by engine and status."""
    rows = (
        AnalysisJob.objects
        .values("engine", "status")
        .annotate(count=Count("id"))
        .order_by("engine", "status")
    )
    return list(rows)


def recent_jobs(limit: int = 100) -> list[dict]:
    """Retrieve the most recent analysis jobs with key metrics."""
    qs = (
        AnalysisJob.objects
        .order_by("-id")
        .values(
            "id", "engine", "status", "game_id", "depth",
            "runpod_job_id", "submitted_at", "duration_seconds",
            "retry_count", "error_message",
        )[:limit]
    )
    return list(qs)


def worker_heartbeats() -> list[dict]:
    """Retrieve status and health metrics of all active workers."""
    return list(
        WorkerHeartbeat.objects
        .order_by("-last_seen")
        .values("worker_id", "status", "last_seen", "current_game_id",
                "jobs_completed", "jobs_failed", "cpu_model", "cpu_cores")
    )


def runpod_health(engine: str) -> tuple[dict | None, str | None]:
    """Call RunPod health endpoint. Returns (metrics_dict, error_str)."""
    import os
    env_map = {
        "stockfish": ("RUNPOD_STOCKFISH_ENDPOINT_ID", "RUNPOD_ENDPOINT_ID"),
        "lc0": ("RUNPOD_LC0_ENDPOINT_ID",),
    }
    endpoint_id = None
    for key in env_map.get(engine, ()):
        endpoint_id = os.environ.get(key, "").strip() or None
        if endpoint_id:
            break

    if not endpoint_id:
        return None, f"Endpoint ID not configured for {engine}"

    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        return None, "RUNPOD_API_KEY not set"

    try:
        import runpod  # type: ignore
        runpod.api_key = api_key
        data = runpod.Endpoint(endpoint_id).health(timeout=5)
    except ImportError:
        return None, "runpod package not installed"
    except Exception as exc:
        return None, f"Health request failed: {exc}"

    jobs = data.get("jobs", {}) or {}
    workers = data.get("workers", {}) or {}
    return {
        "jobs_in_queue": int(jobs.get("inQueue", 0) or 0),
        "jobs_in_progress": int(jobs.get("inProgress", 0) or 0),
        "jobs_completed": int(jobs.get("completed", 0) or 0),
        "jobs_failed": int(jobs.get("failed", 0) or 0),
        "workers_idle": int(workers.get("idle", 0) or 0),
        "workers_running": int(workers.get("running", 0) or 0),
    }, None
