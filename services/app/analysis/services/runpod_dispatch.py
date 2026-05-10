"""
Title: runpod_dispatch.py — Submit AnalysisJob to RunPod serverless endpoint
Description: Pure function that builds the engine-specific payload and calls
    runpod.Endpoint.run(). Returns the RunPod job id string. The caller is
    responsible for acquiring a row lock and transitioning the AnalysisJob
    status after a successful return.
Changelog:
    2026-05-10: Initial — Task A4 of scrap-dispatchers plan.
"""
from __future__ import annotations

import runpod
from django.conf import settings

from analysis.models import AnalysisJob


def _build_payload(job: AnalysisJob) -> dict:
    """Build the engine-specific RunPod payload for one AnalysisJob.

    Args:
        job: The AnalysisJob to build a payload for. job.game.pgn must be non-empty.

    Returns:
        dict: Payload dict ready to pass to runpod.Endpoint.run().

    Side effects:
        Reads ANALYSIS_THREADS, ANALYSIS_HASH_MB, LC0_NODES, and LC0_NETWORK
        from Django settings. Falls back to safe defaults if any are absent.
    """
    if job.engine == "stockfish":
        return {
            "job_id": job.id,
            "pgn": job.game.pgn,
            "depth": job.depth,
            "threads": int(getattr(settings, "ANALYSIS_THREADS", 8)),
            "hash_mb": int(getattr(settings, "ANALYSIS_HASH_MB", 2048)),
        }

    # Lc0 / any other neural engine
    payload: dict = {
        "job_id": job.id,
        "pgn": job.game.pgn,
        "nodes": job.nodes if job.nodes else int(getattr(settings, "LC0_NODES", 25000)),
    }
    network = getattr(settings, "LC0_NETWORK", "") or ""
    if network:
        payload["weights_path"] = network
    return payload


def _endpoint_id(engine: str) -> str:
    """Return the configured RunPod endpoint id for an engine.

    Args:
        engine: Engine name string (e.g. "stockfish" or "lc0").

    Returns:
        str: Non-empty RunPod endpoint id from Django settings.

    Raises:
        ValueError: If the engine name is not recognised.
        RuntimeError: If the settings value for this engine is empty or absent.
    """
    if engine == "stockfish":
        ep = getattr(settings, "RUNPOD_STOCKFISH_ENDPOINT_ID", "") or ""
    elif engine == "lc0":
        ep = getattr(settings, "RUNPOD_LC0_ENDPOINT_ID", "") or ""
    else:
        raise ValueError(f"Unknown engine: {engine!r}")

    if not ep:
        raise RuntimeError(
            f"RunPod endpoint id not configured for engine={engine!r}. "
            "Set RUNPOD_STOCKFISH_ENDPOINT_ID or RUNPOD_LC0_ENDPOINT_ID in the environment."
        )
    return ep


def submit_job_to_runpod(job: AnalysisJob) -> str:
    """Submit one AnalysisJob to RunPod and return the RunPod job id.

    Builds an engine-specific payload, selects the endpoint id from Django
    settings, and calls runpod.Endpoint(endpoint_id).run(payload). Does NOT
    mutate the AnalysisJob — the caller is responsible for acquiring a row lock
    and transitioning status after this function returns successfully.

    Args:
        job: The pending AnalysisJob to dispatch. job.game.pgn must be non-empty.

    Returns:
        str: The RunPod job id from run_request.job_id.

    Raises:
        RuntimeError: If job.game.pgn is empty, or the engine's endpoint id is
            not configured in Django settings.
        ValueError: If the engine name is not recognised.
        Exception: Any exception raised by the runpod SDK propagates to the caller.
    """
    if not job.game.pgn:
        raise RuntimeError(f"AnalysisJob {job.id!r} has no PGN — cannot dispatch to RunPod")

    payload = _build_payload(job)
    endpoint = runpod.Endpoint(_endpoint_id(job.engine))
    run_request = endpoint.run(payload)
    return run_request.job_id
