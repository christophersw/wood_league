"""
Title: test_display.py — Unit tests for the live worker display
Description:
    Covers the issue #44 additions to :mod:`local_worker.display`:
    the per-ply depth/nodes/seconds readout woven into the move-progress
    label, and the debug-only "last debug log line" panel.

Changelog:
    2026-05-13: Initial creation (issue #44).
"""
from __future__ import annotations

from loguru import logger

from local_worker.display import (
    DisplayHandle,
    _format_nodes,
    worker_display,
)
from local_worker.loop import WorkerStats


def test_format_nodes_compact_units() -> None:
    """_format_nodes shrinks large counts into kilo/mega units."""
    assert _format_nodes(None) == ""
    assert _format_nodes(42) == "42"
    assert _format_nodes(2_500) == "2.5k"
    assert _format_nodes(1_234_567) == "1.2M"


def test_advance_move_includes_depth_nodes_seconds() -> None:
    """advance_move pipes per-ply stats into the progress description."""
    stats = WorkerStats()
    with worker_display(stats) as display:
        display.set_job("g-1", "stockfish", total_moves=4)
        display.advance_move(1, 4, san="e4", depth=20, seconds=0.42)
        suffix = display._format_ply_extras()
    assert "d=20" in suffix
    assert "t=0.42s/ply" in suffix


def test_debug_panel_captures_last_log_line() -> None:
    """When debug=True a loguru sink feeds the "last debug line" buffer."""
    stats = WorkerStats()
    with worker_display(stats, debug=True) as display:
        assert display._debug_enabled is True
        logger.debug("worker heartbeat 7")
    assert "worker heartbeat 7" in display._last_debug_line


def test_debug_disabled_skips_panel() -> None:
    """Without debug=True the panel is not rendered and no sink is added."""
    stats = WorkerStats()
    sinks_before = len(getattr(logger, "_core").handlers)
    with worker_display(stats) as display:
        assert display._debug_enabled is False
        assert isinstance(display, DisplayHandle)
        sinks_during = len(getattr(logger, "_core").handlers)
    assert sinks_during == sinks_before
