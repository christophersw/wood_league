"""
Title: test_heartbeat_message.py — Tests for the richer heartbeat status string
Description:
    Verifies the ``build_heartbeat_status`` helper added in issue #85
    renders ``processed=N`` always, appends ``avg_s`` only after at
    least one game has been processed, and appends ``cache_hits=X%``
    only after the eval cache has served at least one lookup.

Changelog:
    2026-05-14: Initial creation for issue #85.
"""
from __future__ import annotations

from local_worker.loop import WorkerStats, build_heartbeat_status


def test_status_message_includes_processed_count_when_empty() -> None:
    """A fresh session emits ``processed=0`` and nothing else."""
    stats = WorkerStats()

    message = build_heartbeat_status(stats)

    assert message == "processed=0"
    assert "avg_s" not in message
    assert "cache_hits" not in message


def test_status_message_omits_avg_until_first_game() -> None:
    """``avg_s`` only appears once at least one game has been processed."""
    stats = WorkerStats()
    stats.record_game("stockfish", 42.0)

    message = build_heartbeat_status(stats)

    assert message.startswith("processed=1")
    assert "avg_s=42.0" in message


def test_status_message_avg_seconds_uses_one_decimal() -> None:
    """``avg_s`` is rendered to a single decimal place across multiple games."""
    stats = WorkerStats()
    stats.record_game("stockfish", 30.0)
    stats.record_game("lc0", 46.5)  # avg = 38.25 → "38.2"

    message = build_heartbeat_status(stats)

    assert "processed=2" in message
    assert "avg_s=38.2" in message


def test_status_message_omits_cache_hits_when_no_lookups() -> None:
    """``cache_hits`` is suppressed until at least one cache lookup occurred."""
    stats = WorkerStats()
    stats.record_game("stockfish", 12.0)
    # No cache lookups recorded — record_cache never called.

    message = build_heartbeat_status(stats)

    assert "cache_hits" not in message


def test_status_message_includes_cache_hits_percent() -> None:
    """A non-empty cache yields a ``cache_hits=<percent>%`` field."""
    stats = WorkerStats()
    stats.record_game("stockfish", 20.0)
    stats.record_cache(hits=42, lookups=100)

    message = build_heartbeat_status(stats)

    assert "cache_hits=42%" in message


def test_status_message_cache_hits_rounds_to_whole_percent() -> None:
    """Hit-rate is rounded to the nearest whole percent (3/7 ≈ 43%)."""
    stats = WorkerStats()
    stats.record_game("lc0", 8.0)
    stats.record_cache(hits=3, lookups=7)

    message = build_heartbeat_status(stats)

    assert "cache_hits=43%" in message
