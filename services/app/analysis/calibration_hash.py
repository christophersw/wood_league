"""
Title: calibration_hash.py — Canonical lc0 sampler settings + stable hash
Description:
    Phase A of issue #161. Per-network draw-rate calibrations are keyed by
    ``(network_name, settings_hash)`` so a calibration measured under one set
    of sampler parameters cannot be reused after those parameters change.

    `current_lc0_sampler_settings` materializes the canonical settings dict
    from Django settings; `current_lc0_settings_hash` hashes its canonical
    JSON serialization with sha256. Both are deterministic — bumping any
    contributing setting (including `WL_LC0_DRAW_RATE_SAMPLER_VERSION`)
    invalidates every existing NetworkCalibration row.

Changelog:
    2026-05-19 (#161/A): Initial — sampler settings + settings_hash helper.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.conf import settings


def current_lc0_sampler_settings() -> dict[str, Any]:
    """Return the canonical lc0 draw-rate sampler settings dict.

    Returns:
        dict[str, Any]: A new dict with keys ``sem_target`` (float),
            ``nodes`` (int), ``max_positions`` (int), ``sampler_version`` (str).
            Keys are stable across calls; values reflect current Django settings.
    """
    return {
        "sem_target": float(settings.WL_LC0_DRAW_RATE_SEM_TARGET),
        "nodes": int(settings.WL_LC0_DRAW_RATE_NODES),
        "max_positions": int(settings.WL_LC0_DRAW_RATE_MAX_POSITIONS),
        "sampler_version": str(settings.WL_LC0_DRAW_RATE_SAMPLER_VERSION),
    }


def canonical_settings_json(settings_dict: dict[str, Any]) -> str:
    """Serialize a settings dict to canonical (sorted, separator-free) JSON.

    Args:
        settings_dict: A JSON-serializable mapping. Key order is irrelevant —
            the output is always sorted by key.

    Returns:
        str: Canonical JSON string with sorted keys and ``(",", ":")``
            separators. Stable across Python versions for hashing purposes.
    """
    return json.dumps(settings_dict, sort_keys=True, separators=(",", ":"))


def current_lc0_settings_hash() -> str:
    """Return the sha256 hex digest of the current canonical sampler settings.

    Returns:
        str: 64-character lowercase hex sha256 of
            ``canonical_settings_json(current_lc0_sampler_settings())``.
    """
    payload = canonical_settings_json(current_lc0_sampler_settings())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
