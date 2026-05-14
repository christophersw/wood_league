"""
Title: app/runpod_client.py — Thin REST client for RunPod pod lifecycle
Description:
    Single-purpose helper that calls RunPod's start-pod REST endpoint
    (POST https://rest.runpod.io/v1/pods/{pod_id}/start) from the Django
    admin "Start worker pod" action. Mirrors the shape used by
    services/local_worker/local_worker/runpod_lifecycle.py but lives in
    the app service so the orchestrator can wake a stopped worker pod
    on demand.

    The function never raises — network and HTTP errors are converted to
    a structured dict ``{ok, status_code, message}`` so the admin view
    can render a predictable JSON response. One attempt, no retries.

Changelog:
    2026-05-14: Initial — admin start-pod endpoint (issue #83).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

_RUNPOD_START_URL = "https://rest.runpod.io/v1/pods/{pod_id}/start"
_BODY_TRUNCATE_CHARS = 500


def _truncate_body(body: Any) -> str:
    """Return a string-coerced response body trimmed to a safe log length.

    Args:
        body: Any object — typically the ``response.text`` from httpx but
            may also be an exception message or other diagnostic string.

    Returns:
        str: ``str(body)`` truncated to ``_BODY_TRUNCATE_CHARS`` characters
            so that WARNING-level logs do not flood with multi-KB payloads.
    """
    text = "" if body is None else str(body)
    if len(text) <= _BODY_TRUNCATE_CHARS:
        return text
    return text[:_BODY_TRUNCATE_CHARS] + "...[truncated]"


def start_pod(pod_id: str, api_key: str, *, timeout: float = 10.0) -> dict:
    """Call RunPod's start-pod REST endpoint for the given pod.

    Issues a single POST request to
    ``https://rest.runpod.io/v1/pods/{pod_id}/start`` with a Bearer token.
    No retries, no polling. Network and HTTP errors are caught and
    surfaced via the return value rather than raised.

    Args:
        pod_id: RunPod pod identifier to start.
        api_key: RunPod API key with start permission on this pod. Sent
            as ``Authorization: Bearer <api_key>``.
        timeout: HTTP request timeout in seconds. Defaults to 10.

    Returns:
        dict: ``{"ok": bool, "status_code": int, "message": str}``.
            ``ok`` is True on a 2xx response. ``status_code`` is 0 on
            network errors. ``message`` echoes RunPod's status text or
            the truncated response body / exception message.

    Side effects:
        Emits a WARNING log entry on non-2xx responses or network errors,
        including the truncated response body. Never raises.
    """
    url = _RUNPOD_START_URL.format(pod_id=pod_id)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    try:
        response = httpx.post(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        message = _truncate_body(exc)
        _LOGGER.warning(
            "runpod start_pod network error pod=%s err=%s", pod_id, message,
        )
        return {"ok": False, "status_code": 0, "message": message}

    if 200 <= response.status_code < 300:
        return {
            "ok": True,
            "status_code": response.status_code,
            "message": "started",
        }

    body = _truncate_body(response.text)
    _LOGGER.warning(
        "runpod start_pod non-2xx pod=%s status=%s body=%s",
        pod_id, response.status_code, body,
    )
    return {
        "ok": False,
        "status_code": response.status_code,
        "message": body or response.reason_phrase or "runpod error",
    }
