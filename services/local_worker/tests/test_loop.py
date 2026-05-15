"""
Title: test_loop.py — Tests for the worker loop stats tracking
Description:
    Tests that WorkerStats accumulates counts correctly and that
    run_one_job dispatches to the right engine analyser.

Changelog:
    2026-05-09: Initial creation
    2026-05-14: Pin the lc0 node-budget fallback chain so jobs with
        depth=N nodes=None still analyse at N nodes/move (issue #111).
"""
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from local_worker import loop as worker_loop
from local_worker.loop import WorkerStats, run_one_job


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


# ---------------------------------------------------------------------------
# lc0 node-budget fallback (issue #111)
# ---------------------------------------------------------------------------


@dataclass
class _StubJob:
    """Minimal Job stand-in for run_one_job dispatch tests."""

    id: int = 1
    game_id: str = "game-1"
    pgn: str = ""
    engine: str = "lc0"
    depth: int = 0
    nodes: int | None = None


class _StubClient:
    """No-op WorkerClient that captures complete/fail calls."""

    def __init__(self) -> None:
        self.completed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    def complete_lc0(self, **kwargs: Any) -> None:
        self.completed.append(kwargs)

    def complete_stockfish(self, **kwargs: Any) -> None:
        self.completed.append(kwargs)

    def fail(self, **kwargs: Any) -> None:
        self.failed.append(kwargs)


def _settings_for_lc0(default_nodes: int = 10000) -> SimpleNamespace:
    """Build a Settings stand-in covering only the fields run_one_job touches."""
    return SimpleNamespace(
        worker_id="test-worker",
        lc0_path="/fake/lc0",
        lc0_nodes=default_nodes,
        lc0_weights_path="/fake/net.pb.gz",
        lc0_backend="cuda-fp16",
        syzygy_path="/fake/syzygy",
        eval_cache_path=None,
        eval_cache_max_mb=0,
        stockfish_path="/fake/stockfish",
        stockfish_depth=20,
        stockfish_threads=1,
        stockfish_hash_mb=128,
    )


def _patch_lc0_analyze(
    monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
) -> None:
    """Replace the lc0 analyser + payload builder with capture stubs."""

    def fake_analyze(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(worker_loop, "lc0_analyze", fake_analyze)
    monkeypatch.setattr(worker_loop, "build_lc0_payload", lambda *_a, **_k: {})
    monkeypatch.setattr(worker_loop, "_open_eval_cache", lambda *_a, **_k: None)


def test_lc0_uses_job_depth_when_nodes_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #111: server emits depth=25000 nodes=None — run at 25k, not the default.

    Reproduces the RunPod log where every lc0 job arrived with
    ``depth=25000 nodes=None`` and was silently analysed at 10,000
    nodes/move because the worker only consulted ``job.nodes``.
    """
    captured: dict[str, Any] = {}
    _patch_lc0_analyze(monkeypatch, captured)

    ok = run_one_job(
        job=_StubJob(depth=25000, nodes=None),
        settings=_settings_for_lc0(default_nodes=10000),
        stats=WorkerStats(),
        client=_StubClient(),
    )

    assert ok is True
    assert captured["nodes"] == 25000


def test_lc0_prefers_explicit_nodes_over_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``job.nodes`` still wins when the server starts emitting it directly."""
    captured: dict[str, Any] = {}
    _patch_lc0_analyze(monkeypatch, captured)

    run_one_job(
        job=_StubJob(depth=25000, nodes=50000),
        settings=_settings_for_lc0(default_nodes=10000),
        stats=WorkerStats(),
        client=_StubClient(),
    )

    assert captured["nodes"] == 50000


def test_lc0_falls_back_to_settings_when_both_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the job carries neither nodes nor depth, use settings.lc0_nodes."""
    captured: dict[str, Any] = {}
    _patch_lc0_analyze(monkeypatch, captured)

    run_one_job(
        job=_StubJob(depth=0, nodes=None),
        settings=_settings_for_lc0(default_nodes=12345),
        stats=WorkerStats(),
        client=_StubClient(),
    )

    assert captured["nodes"] == 12345
