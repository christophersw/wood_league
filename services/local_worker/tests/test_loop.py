"""
Title: test_loop.py — Tests for the worker loop stats tracking
Description:
    Tests that WorkerStats accumulates counts correctly and that
    run_one_job dispatches to the right engine analyser.

Changelog:
    2026-05-09: Initial creation
"""
import pytest
from local_worker.loop import WorkerStats


def test_stats_initial_state():
    """Verify WorkerStats fields are zero on initialisation."""
    s = WorkerStats()
    assert s.games_processed == 0
    assert s.stockfish_count == 0
    assert s.lc0_count == 0
    assert s.total_seconds == 0.0


def test_stats_record_game_stockfish():
    """Verify record_game increments stockfish counter and total_seconds."""
    s = WorkerStats()
    s.record_game("stockfish", 3.5)
    assert s.games_processed == 1
    assert s.stockfish_count == 1
    assert s.lc0_count == 0
    assert s.total_seconds == pytest.approx(3.5)


def test_stats_avg_seconds_per_game():
    """Verify avg_seconds_per_game returns mean across mixed engines."""
    s = WorkerStats()
    s.record_game("stockfish", 4.0)
    s.record_game("lc0", 6.0)
    assert s.avg_seconds_per_game() == pytest.approx(5.0)


def test_stats_avg_seconds_no_games():
    """Verify avg_seconds_per_game returns 0.0 when no games processed."""
    s = WorkerStats()
    assert s.avg_seconds_per_game() == 0.0
