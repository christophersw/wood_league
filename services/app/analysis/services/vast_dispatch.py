"""
Title: vast_dispatch.py — thin REST client for vast.ai instance lifecycle
Description:
    Single-purpose helper the reconcile cron uses to search offers,
    create an instance from a template hash, destroy an instance, and
    list instances. Mirrors app/runpod_client.py: network/HTTP errors
    become structured dicts, never raised — EXCEPT search, which raises
    NoVastOfferError when nothing qualifies (a real decision the caller
    must branch on). The VAST_API_KEY is never logged.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

_BASE = "https://console.vast.ai/api/v0"
_BUNDLES_URL = f"{_BASE}/bundles/"
_ASK_URL = f"{_BASE}/asks/{{offer_id}}/"
_INSTANCE_URL = f"{_BASE}/instances/{{instance_id}}/"
_INSTANCES_URL = f"{_BASE}/instances/"
_BODY_TRUNCATE_CHARS = 500


class NoVastOfferError(RuntimeError):
    """Raised when no vast offer matches the GPU + price ceiling."""


def _truncate(body: Any) -> str:
    """Return str(body) trimmed to a safe log length (never the api key)."""
    text = "" if body is None else str(body)
    if len(text) <= _BODY_TRUNCATE_CHARS:
        return text
    return text[:_BODY_TRUNCATE_CHARS] + "...[truncated]"


def _headers(api_key: str) -> dict:
    """Return auth + json headers. The key is used here, never logged."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def search_cheapest_offer(
    *, api_key: str, gpu_name: str, max_dph: float, timeout: float = 20.0,
) -> dict:
    """Return the cheapest on-demand offer for ``gpu_name`` at/under ``max_dph``.

    Args:
        api_key: vast API key (Bearer). Never logged.
        gpu_name: vast GPU model name, e.g. ``"L40S"``.
        max_dph: maximum acceptable $/hr (``dph_total``) ceiling.
        timeout: HTTP timeout in seconds.

    Returns:
        dict: the chosen offer dict (has at least ``id`` and ``dph_total``).

    Raises:
        NoVastOfferError: on a non-2xx response, a network error, an empty
            result, or when every offer exceeds ``max_dph``.
    """
    # vast.ai's search-offers endpoint is POST /api/v0/bundles/ with a
    # JSON filter body (NOT a GET with query params) — verified against
    # docs.vast.ai/api-reference/search/search-offers.
    body = {
        "limit": 64,
        "type": "ondemand",
        "rentable": {"eq": True},
        "gpu_name": {"eq": gpu_name},
        "order": [["dph_total", "asc"]],
    }
    try:
        resp = httpx.post(_BUNDLES_URL, headers=_headers(api_key),
                          json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast search network error gpu=%s err=%s",
                        gpu_name, _truncate(exc))
        raise NoVastOfferError("vast search network error") from exc
    if not 200 <= resp.status_code < 300:
        _LOGGER.warning("vast search non-2xx gpu=%s status=%s body=%s",
                        gpu_name, resp.status_code, _truncate(resp.text))
        raise NoVastOfferError(f"vast search status {resp.status_code}")
    offers = (resp.json() or {}).get("offers") or []
    affordable = sorted(
        (o for o in offers if o.get("dph_total") is not None
         and float(o["dph_total"]) <= max_dph),
        key=lambda o: float(o["dph_total"]),
    )
    if not affordable:
        _LOGGER.warning("vast search no offer gpu=%s max_dph=%s offers=%d",
                        gpu_name, max_dph, len(offers))
        raise NoVastOfferError(
            f"no {gpu_name} offer at/under {max_dph} $/hr")
    return affordable[0]


def create_instance(
    *, api_key: str, offer_id: int, template_hash: str, label: str,
    env: dict, timeout: float = 30.0,
) -> dict:
    """Create an instance from a template hash on the given offer.

    ``env`` is sent as a JSON object: vast merges it with the template's
    env, request keys overriding template keys (verified behaviour).

    Args:
        api_key: vast API key (Bearer). Never logged.
        offer_id: offer id from :func:`search_cheapest_offer`.
        template_hash: ``VAST_TEMPLATE_HASH`` (version-pinned config).
        label: instance label (used for orphan discovery).
        env: per-run env dict (WL_CAMPAIGN_ID, WLW_MAX_JOBS, WL_SCHEDULE_ID).
        timeout: HTTP timeout in seconds.

    Returns:
        dict: ``{"ok", "status_code", "message", "vast_instance_id"}``.
            ``vast_instance_id`` is the str of vast ``new_contract`` on
            success, else None. Never raises.
    """
    url = _ASK_URL.format(offer_id=offer_id)
    payload = {"template_hash_id": template_hash, "label": label, "env": env}
    try:
        resp = httpx.put(url, headers=_headers(api_key), json=payload,
                         timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast create network error offer=%s err=%s",
                        offer_id, _truncate(exc))
        return {"ok": False, "status_code": 0,
                "message": _truncate(exc), "vast_instance_id": None}
    if 200 <= resp.status_code < 300:
        contract = (resp.json() or {}).get("new_contract")
        if contract is None:
            _LOGGER.warning("vast create 2xx but no new_contract offer=%s",
                            offer_id)
            return {"ok": False, "status_code": resp.status_code,
                    "message": "no new_contract in response",
                    "vast_instance_id": None}
        return {"ok": True, "status_code": resp.status_code,
                "message": "created", "vast_instance_id": str(contract)}
    body = _truncate(resp.text)
    _LOGGER.warning("vast create non-2xx offer=%s status=%s body=%s",
                    offer_id, resp.status_code, body)
    return {"ok": False, "status_code": resp.status_code,
            "message": body or "vast create error", "vast_instance_id": None}


def destroy_instance(
    *, api_key: str, vast_instance_id: str, timeout: float = 20.0,
) -> dict:
    """Destroy an instance. Idempotent: 404 (already gone) is success.

    Args:
        api_key: vast API key (Bearer). Never logged.
        vast_instance_id: the vast contract/instance id.
        timeout: HTTP timeout in seconds.

    Returns:
        dict: ``{"ok", "status_code", "message"}``. Never raises.
    """
    url = _INSTANCE_URL.format(instance_id=vast_instance_id)
    try:
        resp = httpx.delete(url, headers=_headers(api_key), timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast destroy network error inst=%s err=%s",
                        vast_instance_id, _truncate(exc))
        return {"ok": False, "status_code": 0, "message": _truncate(exc)}
    if 200 <= resp.status_code < 300 or resp.status_code == 404:
        return {"ok": True, "status_code": resp.status_code,
                "message": "destroyed"}
    body = _truncate(resp.text)
    _LOGGER.warning("vast destroy non-2xx inst=%s status=%s body=%s",
                    vast_instance_id, resp.status_code, body)
    return {"ok": False, "status_code": resp.status_code,
            "message": body or "vast destroy error"}


def list_instances(*, api_key: str, timeout: float = 20.0) -> list[dict]:
    """List the authenticated account's instances.

    Args:
        api_key: vast API key (Bearer). Never logged.
        timeout: HTTP timeout in seconds.

    Returns:
        list[dict]: the ``instances`` array, or [] on any error.
    """
    try:
        resp = httpx.get(_INSTANCES_URL, headers=_headers(api_key),
                        timeout=timeout)
    except httpx.HTTPError as exc:
        _LOGGER.warning("vast list network error err=%s", _truncate(exc))
        return []
    if not 200 <= resp.status_code < 300:
        _LOGGER.warning("vast list non-2xx status=%s body=%s",
                        resp.status_code, _truncate(resp.text))
        return []
    return (resp.json() or {}).get("instances") or []
