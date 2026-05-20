"""
Title: test_calibration_hash.py — Tests for lc0 sampler settings_hash helper
Description:
    Phase A of issue #161. The app pins per-network draw-rate calibrations to
    the exact sampler settings used to measure them. `current_lc0_sampler_settings`
    returns the canonical settings dict; `current_lc0_settings_hash` returns the
    sha256 of its canonical JSON encoding. Bumping any input constant — including
    `WL_LC0_DRAW_RATE_SAMPLER_VERSION` — invalidates the hash and therefore all
    existing calibrations keyed against it.

Changelog:
    2026-05-19 (#161/A): Initial failing test for settings_hash helper.
"""
from __future__ import annotations

import hashlib
import json

import pytest
from django.test import override_settings

from analysis.calibration_hash import (
    canonical_settings_json,
    current_lc0_sampler_settings,
    current_lc0_settings_hash,
)


def test_sampler_settings_shape() -> None:
    """The sampler settings dict surfaces every input the worker needs."""
    settings = current_lc0_sampler_settings()
    assert set(settings) == {
        "sem_target",
        "nodes",
        "max_positions",
        "sampler_version",
    }
    assert isinstance(settings["sem_target"], float)
    assert isinstance(settings["nodes"], int)
    assert isinstance(settings["max_positions"], int)
    assert isinstance(settings["sampler_version"], str)


def test_hash_is_sha256_of_canonical_json() -> None:
    """Hash matches sha256(canonical_json(current_lc0_sampler_settings()))."""
    settings = current_lc0_sampler_settings()
    expected = hashlib.sha256(
        json.dumps(settings, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert current_lc0_settings_hash() == expected


def test_canonical_json_is_sorted_compact() -> None:
    """canonical_settings_json produces sorted, separator-free JSON for stable hashing."""
    raw = canonical_settings_json({"b": 2, "a": 1})
    assert raw == '{"a":1,"b":2}'


@override_settings(WL_LC0_DRAW_RATE_NODES=4242)
def test_hash_changes_when_setting_changes() -> None:
    """Changing any underlying setting must change the hash."""
    hash_a = current_lc0_settings_hash()
    with override_settings(WL_LC0_DRAW_RATE_NODES=1234):
        hash_b = current_lc0_settings_hash()
    assert hash_a != hash_b


@override_settings(WL_LC0_DRAW_RATE_SAMPLER_VERSION="v1")
def test_sampler_version_invalidates_hash() -> None:
    """Bumping sampler_version invalidates every calibration keyed by old hash."""
    hash_v1 = current_lc0_settings_hash()
    with override_settings(WL_LC0_DRAW_RATE_SAMPLER_VERSION="v2"):
        hash_v2 = current_lc0_settings_hash()
    assert hash_v1 != hash_v2


@pytest.mark.parametrize("nodes", [800, 1600, 3200])
def test_hash_stable_across_calls(nodes: int) -> None:
    """Hash is deterministic — repeated calls with same settings return identical hash."""
    with override_settings(WL_LC0_DRAW_RATE_NODES=nodes):
        assert current_lc0_settings_hash() == current_lc0_settings_hash()
