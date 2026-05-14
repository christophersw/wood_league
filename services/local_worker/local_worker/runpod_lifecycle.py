"""
Title: runpod_lifecycle.py — Self-stop hook for RunPod-hosted workers
Description:
    Provides a one-shot helper that asks RunPod's REST API to stop the
    current pod after the worker has drained its queue. Designed for
    cost-conscious deployments on spot / on-demand pods that should not
    continue billing once there is no work to do.

    The module intentionally never raises and never retries: cloud calls
    are best-effort, and a missed stop is recoverable by stopping the pod
    manually from the RunPod console.

Changelog:
    2026-05-14: Initial creation for issue #81.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from local_worker.config import Settings

logger = logging.getLogger(__name__)

# RunPod REST API endpoint for stopping a pod. Documented at
# https://rest.runpod.io/v1/docs#tag/pods/POST/pods/{podId}/stop
_STOP_URL_TEMPLATE = "https://rest.runpod.io/v1/pods/{pod_id}/stop"

# Cap on logged response bodies so a misbehaving upstream cannot flood
# the worker logs with megabytes of HTML.
_BODY_LOG_LIMIT = 500


def stop_self(pod_id: str, api_key: str, *, timeout: float = 10.0) -> bool:
    """Call RunPod's stop-pod REST endpoint for this pod.

    Args:
        pod_id: RunPod pod identifier (the ``RUNPOD_POD_ID`` env value).
        api_key: RunPod API key with stop permission on this pod.
        timeout: HTTP timeout in seconds.

    Returns:
        True if RunPod returned 2xx; False on any other status or network
        error. Never raises — the caller should not be punished for cloud
        flakiness.
    """
    url = _STOP_URL_TEMPLATE.format(pod_id=pod_id)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    logger.info("runpod self-stop: POST %s", url)
    try:
        response = httpx.post(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        logger.warning("runpod self-stop: network error: %s", exc)
        return False

    if 200 <= response.status_code < 300:
        logger.info("runpod self-stop: success (status=%s)", response.status_code)
        return True

    body = (response.text or "")[:_BODY_LOG_LIMIT]
    logger.warning(
        "runpod self-stop: failed (status=%s): %s",
        response.status_code,
        body,
    )
    return False


def resolve_pod_id(settings: Settings) -> Optional[str]:
    """Determine the pod id to stop, preferring explicit settings over env.

    Args:
        settings: Loaded worker settings (may carry an explicit pod id).

    Returns:
        The explicit ``settings.runpod_pod_id`` if non-empty; otherwise the
        ``RUNPOD_POD_ID`` env var injected by RunPod; otherwise ``None``.
    """
    explicit = (settings.runpod_pod_id or "").strip()
    if explicit:
        return explicit
    injected = (os.environ.get("RUNPOD_POD_ID") or "").strip()
    return injected or None
