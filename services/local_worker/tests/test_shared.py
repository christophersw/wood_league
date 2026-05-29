"""
Title: test_shared.py — Unit tests for local_worker._shared helpers
Description:
    Covers ``read_gpu_count()``, the shared ``WL_GPU_COUNT`` parser used by
    both the Stockfish fan-out planner and the lc0 per-process self-sizing
    so they agree on how many lc0 processes share the host (#223).

Changelog:
    2026-05-28: Initial creation (#223).
"""
from __future__ import annotations

import pytest

from local_worker._shared import read_gpu_count


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", 1),
        ("2", 2),
        ("  4 ", 4),
    ],
)
def test_read_gpu_count_parses_positive_int(monkeypatch, raw, expected):
    monkeypatch.setenv("WL_GPU_COUNT", raw)
    assert read_gpu_count() == expected


@pytest.mark.parametrize("raw", ["", "0", "-3", "two", "1.5", "abc"])
def test_read_gpu_count_falls_back_to_one(monkeypatch, raw):
    """Missing, non-numeric, or non-positive values floor at a single GPU."""
    monkeypatch.setenv("WL_GPU_COUNT", raw)
    assert read_gpu_count() == 1


def test_read_gpu_count_absent_env_defaults_to_one(monkeypatch):
    monkeypatch.delenv("WL_GPU_COUNT", raising=False)
    assert read_gpu_count() == 1
