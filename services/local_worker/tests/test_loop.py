"""
Title: test_loop.py — Tests for the worker loop stats tracking
Description:
    Tests that WorkerStats accumulates counts correctly and that
    run_one_job dispatches to the right engine analyser. Also covers
    run_batch one-at-a-time checkout behaviour and max_jobs cap (E-T2).

Changelog:
    2026-05-09: Initial creation
    2026-05-14: Pin the lc0 node-budget fallback chain so jobs with
        depth=N nodes=None still analyse at N nodes/move (issue #111).
    2026-05-16: Add run_batch TDD tests for one-at-a-time checkout and
        max_jobs run cap (task E-T2).
"""
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from local_worker import loop as worker_loop
from local_worker.loop import WorkerStats, run_batch, run_one_job


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


# ---------------------------------------------------------------------------
# run_batch: one-at-a-time checkout and max_jobs cap (E-T2)
# ---------------------------------------------------------------------------


class _FakeCheckoutClient:
    """Fake WorkerClient that serves pre-loaded jobs one checkout call at a time.

    Attributes:
        checkout_batch_sizes: Accumulates the ``batch_size`` arg from every
            ``checkout()`` call so tests can assert the values.
        completed: Tracks ``complete_*`` calls like ``_StubClient``.
        failed: Tracks ``fail`` calls.
        _queue: Remaining jobs to serve (FIFO).
    """

    def __init__(self, jobs: list[Any]) -> None:
        self._queue = list(jobs)
        self.checkout_batch_sizes: list[int] = []
        self.completed: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    def checkout(self, *, engine: str, worker_id: str, batch_size: int, game_id: Any, dispatch_mode: str) -> list[Any]:
        """Return up to batch_size jobs from the queue, recording the requested size.

        Args:
            engine: Engine name (unused for test purposes).
            worker_id: Worker identifier (unused).
            batch_size: Requested number of jobs — recorded in ``checkout_batch_sizes``.
            game_id: Specific game id filter (unused).
            dispatch_mode: Pull/push mode (unused).

        Returns:
            List containing the next job, or empty list when queue is exhausted.
        """
        self.checkout_batch_sizes.append(batch_size)
        if not self._queue:
            return []
        return [self._queue.pop(0)]

    def complete_lc0(self, **kwargs: Any) -> None:
        """Record a completed lc0 job."""
        self.completed.append(kwargs)

    def complete_stockfish(self, **kwargs: Any) -> None:
        """Record a completed stockfish job."""
        self.completed.append(kwargs)

    def fail(self, **kwargs: Any) -> None:
        """Record a failed job."""
        self.failed.append(kwargs)

    def heartbeat(self, **kwargs: Any) -> None:
        """Accept heartbeat calls without side effects."""


def _make_batch_settings() -> SimpleNamespace:
    """Build a minimal Settings stand-in for run_batch tests.

    Returns:
        A SimpleNamespace with all fields run_batch / run_one_job need.
    """
    return SimpleNamespace(
        api_url="http://localhost:9999",
        api_key="test-key",
        worker_id="test-worker",
        lc0_path="/fake/lc0",
        lc0_nodes=10000,
        lc0_weights_path="/fake/net.pb.gz",
        lc0_backend="cpu",
        syzygy_path="",
        eval_cache_path=None,
        eval_cache_max_mb=0,
        eval_cache_enabled=False,
        stockfish_path="/fake/stockfish",
        stockfish_depth=20,
        stockfish_threads=1,
        stockfish_hash_mb=128,
    )


def _stub_lc0_jobs(n: int, engine: str = "stockfish") -> list[Any]:
    """Build a list of ``n`` minimal job stubs for the given engine.

    Args:
        n: Number of jobs to generate.
        engine: Engine name for each job.

    Returns:
        List of ``_StubJob`` instances with sequential ids.
    """
    return [_StubJob(id=i, game_id=f"game-{i}", engine=engine) for i in range(1, n + 1)]


def _patch_run_one_job_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace run_one_job with a no-op that always returns True and increments stats.

    This lets run_batch tests control the job queue via the fake client
    without needing real engine binaries.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    def fake_run_one_job(*, job: Any, settings: Any, stats: WorkerStats, client: Any, **kwargs: Any) -> bool:
        stats.record_game(job.engine, 0.1)
        return True

    monkeypatch.setattr(worker_loop, "run_one_job", fake_run_one_job)


# ---------------------------------------------------------------------------
# Test 1: every checkout call requests exactly one job
# ---------------------------------------------------------------------------


def test_run_batch_checkout_requests_one_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every client.checkout call must request batch_size=1 (E-T2 behaviour 1).

    With 3 queued jobs, run_batch should make at least 3 checkout calls and
    every one of those calls must pass batch_size=1.
    """
    _patch_run_one_job_noop(monkeypatch)
    fake_client = _FakeCheckoutClient(_stub_lc0_jobs(3))
    run_batch(
        settings=_make_batch_settings(),
        engines=["stockfish"],
        _client=fake_client,
    )
    assert len(fake_client.checkout_batch_sizes) >= 3
    assert all(sz == 1 for sz in fake_client.checkout_batch_sizes), (
        f"Expected all checkout calls to use batch_size=1, got: {fake_client.checkout_batch_sizes}"
    )


# ---------------------------------------------------------------------------
# Test 2: max_jobs=3 with 10 queued → stats.games_processed == 3
# ---------------------------------------------------------------------------


def test_run_batch_max_jobs_cap_stops_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_jobs=3 with 10 queued jobs must process exactly 3 (E-T2 behaviour 2)."""
    _patch_run_one_job_noop(monkeypatch)
    fake_client = _FakeCheckoutClient(_stub_lc0_jobs(10))
    stats = run_batch(
        settings=_make_batch_settings(),
        engines=["stockfish"],
        max_jobs=3,
        _client=fake_client,
    )
    assert stats.games_processed == 3


# ---------------------------------------------------------------------------
# Test 3: max_jobs=None with 4 queued → drains all 4
# ---------------------------------------------------------------------------


def test_run_batch_no_max_jobs_drains_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """max_jobs=None (default) must drain the full queue of 4 (E-T2 behaviour 3)."""
    _patch_run_one_job_noop(monkeypatch)
    fake_client = _FakeCheckoutClient(_stub_lc0_jobs(4))
    stats = run_batch(
        settings=_make_batch_settings(),
        engines=["stockfish"],
        max_jobs=None,
        _client=fake_client,
    )
    assert stats.games_processed == 4


# ---------------------------------------------------------------------------
# Test 4: lc0 warm engine launched exactly ONCE across N single-job claims
# ---------------------------------------------------------------------------


def test_run_batch_lc0_warm_engine_launched_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """lc0_launch_engine must be called exactly once for an N-job lc0 run (E-T2 behaviour 4).

    With 3 lc0 jobs queued, the warm engine should be launched once at the
    start of _drain_engine_queue, not once per claimed job.
    """
    _patch_run_one_job_noop(monkeypatch)
    launch_calls: list[dict[str, Any]] = []

    class _FakeEngine:
        """Minimal engine stub with a quit() method."""
        def quit(self) -> None:
            pass

    def fake_launch_engine(**kwargs: Any) -> tuple[_FakeEngine, str]:
        launch_calls.append(kwargs)
        return _FakeEngine(), "fake-net"

    monkeypatch.setattr(worker_loop, "lc0_launch_engine", fake_launch_engine)
    fake_client = _FakeCheckoutClient(_stub_lc0_jobs(3, engine="lc0"))
    run_batch(
        settings=_make_batch_settings(),
        engines=["lc0"],
        _client=fake_client,
    )
    assert len(launch_calls) == 1, (
        f"Expected lc0_launch_engine to be called once, was called {len(launch_calls)} times"
    )


# ---------------------------------------------------------------------------
# Test 5: max_jobs=100 + batch_time_minutes=0 → time cap fires first
# ---------------------------------------------------------------------------


def test_run_batch_time_cap_fires_before_max_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """batch_time_minutes=0 (expired immediately) must stop before max_jobs=100 (E-T2 behaviour 5)."""
    _patch_run_one_job_noop(monkeypatch)
    fake_client = _FakeCheckoutClient(_stub_lc0_jobs(100))
    stats = run_batch(
        settings=_make_batch_settings(),
        engines=["stockfish"],
        max_jobs=100,
        batch_time_minutes=0,
        _client=fake_client,
    )
    assert stats.games_processed < 100
