"""
Title: loop.py — Claim-analyse-submit worker loop with stats tracking
Description:
    Implements the main processing loop: checks out jobs from the API,
    dispatches to the appropriate engine analyser, submits results, and
    sends periodic heartbeats. Tracks per-session statistics.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional

from local_worker.worker_client import WorkerClient, WorkerClientError
from local_worker.analysis.stockfish import analyze_pgn as sf_analyze, build_stockfish_payload
from local_worker.analysis.lc0 import analyze_pgn as lc0_analyze, build_lc0_payload
from local_worker.config import Settings

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30.0


@dataclass
class WorkerStats:
    """Tracks per-session analysis statistics."""

    games_processed: int = 0
    stockfish_count: int = 0
    lc0_count: int = 0
    total_seconds: float = 0.0
    errors: int = 0

    def record_game(self, engine: str, elapsed: float) -> None:
        """Record a successfully processed game.

        Args:
            engine: 'stockfish' or 'lc0'.
            elapsed: Wall-clock seconds taken.
        """
        self.games_processed += 1
        self.total_seconds += elapsed
        if engine == "stockfish":
            self.stockfish_count += 1
        else:
            self.lc0_count += 1

    def avg_seconds_per_game(self) -> float:
        """Return average wall-clock seconds per game, or 0.0 if none processed."""
        if self.games_processed == 0:
            return 0.0
        return self.total_seconds / self.games_processed


def _worker_id(settings: Settings) -> str:
    """Return the worker_id to send to the API.

    Args:
        settings: Current worker settings.

    Returns:
        Configured worker_id, or hostname-based fallback truncated to 64 chars.
    """
    if settings.worker_id:
        return settings.worker_id
    return f"local-{socket.gethostname()}"[:64]


def run_one_job(
    *,
    job,
    settings: Settings,
    stats: WorkerStats,
    client: WorkerClient,
    progress_callback: Optional[Callable[[int, int, str, str], None]] = None,
) -> bool:
    """Claim, analyse, and submit a single job.

    Args:
        job: Job dataclass from WorkerClient.checkout().
        settings: Current worker settings.
        stats: WorkerStats to update on completion.
        client: Authenticated WorkerClient for API calls.
        progress_callback: Optional callable(ply, total_plies) for per-move progress.

    Returns:
        True if the job completed successfully, False on error.
    """
    worker_id = _worker_id(settings)
    start = time.monotonic()
    log.info(
        "Starting job %s — engine=%s game=%s depth=%s nodes=%s",
        job.id, job.engine, job.game_id, job.depth, job.nodes,
    )

    # Wrap caller's progress callback to log each move so the log file shows
    # which ply was just analysed (visible feedback even when the rich display
    # is masking stdout).
    def _logging_progress(ply: int, total: int, san: str = "", fen: str = "") -> None:
        log.info(
            "  job %s — move %d/%d %s",
            job.id, ply, total, san or "?",
        )
        if progress_callback:
            progress_callback(ply, total, san, fen)

    try:
        if job.engine == "stockfish":
            result = sf_analyze(
                pgn_text=job.pgn,
                stockfish_path=settings.stockfish_path,
                depth=settings.stockfish_depth,
                threads=settings.stockfish_threads,
                hash_mb=settings.stockfish_hash_mb,
                syzygy_path=settings.syzygy_path,
                progress_callback=_logging_progress,
            )
            payload = build_stockfish_payload(result, worker_id=worker_id)
            client.complete_stockfish(job_id=job.id, worker_id=worker_id, payload=payload)
        elif job.engine == "lc0":
            nodes = job.nodes or settings.lc0_nodes
            result = lc0_analyze(
                pgn_text=job.pgn,
                lc0_path=settings.lc0_path,
                nodes=nodes,
                weights_path=settings.lc0_weights_path,
                syzygy_path=settings.syzygy_path,
                backend=settings.lc0_backend or "cpu",
                progress_callback=_logging_progress,
            )
            payload = build_lc0_payload(result, worker_id=worker_id)
            client.complete_lc0(job_id=job.id, worker_id=worker_id, payload=payload)
        else:
            log.error("Unknown engine: %s — failing job %d", job.engine, job.id)
            client.fail(job_id=job.id, worker_id=worker_id, error=f"Unknown engine: {job.engine}")
            return False

        elapsed = time.monotonic() - start
        stats.record_game(job.engine, elapsed)
        log.info("Job %s complete (%s) in %.1fs", job.id, job.engine, elapsed)
        return True

    except Exception as exc:
        elapsed = time.monotonic() - start
        stats.errors += 1
        log.exception("Failed to process job %d: %s", job.id, exc)
        try:
            client.fail(job_id=job.id, worker_id=worker_id, error=str(exc)[:2000])
        except Exception:
            log.warning("Failed to report failure for job %d", job.id)
        return False


def run_batch(
    *,
    settings: Settings,
    engines: list[str],
    batch_size: int = 5,
    batch_time_minutes: Optional[int] = None,
    game_id: Optional[str] = None,
    on_job_start: Optional[Callable] = None,
    on_job_done: Optional[Callable] = None,
    on_progress: Optional[Callable[[int, int, str, str], None]] = None,
    on_jobs_claimed: Optional[Callable[[list], None]] = None,
    stop_event=None,
) -> WorkerStats:
    """Run the main claim->analyse->submit loop.

    Processes jobs until the batch_time_minutes limit is reached, all queues
    are empty, or stop_event is set. Heartbeats are sent every 30 seconds.

    Args:
        settings: Worker settings (API URL, key, engine paths, etc.).
        engines: List of engines to claim jobs for, e.g. ['stockfish', 'lc0'].
        batch_size: Jobs to claim per checkout call (1-10).
        batch_time_minutes: If set, stop after this many minutes.
        game_id: If set, request a specific game (single checkout).
        on_job_start: Optional callable(job) called before analysis.
        on_job_done: Optional callable(job, success, elapsed) called after.
        on_progress: Optional callable(ply, total_plies) for per-move progress.
        stop_event: Optional threading.Event; loop exits when set.

    Returns:
        WorkerStats with totals for the batch.
    """
    client = WorkerClient(base_url=settings.api_url, api_key=settings.api_key)
    stats = WorkerStats()
    worker_id = _worker_id(settings)
    start_time = time.monotonic()
    last_heartbeat = 0.0

    def _time_limit_exceeded() -> bool:
        """Return True if the batch time limit has been reached."""
        if batch_time_minutes is None:
            return False
        return (time.monotonic() - start_time) >= batch_time_minutes * 60

    def _send_heartbeat(engine: str) -> None:
        """Send a heartbeat if the interval has elapsed.

        Args:
            engine: Currently active engine name.
        """
        nonlocal last_heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= _HEARTBEAT_INTERVAL:
            try:
                client.heartbeat(
                    worker_id=worker_id,
                    engine=engine,
                    status_message=f"processed={stats.games_processed}",
                )
            except WorkerClientError:
                pass
            last_heartbeat = now

    def _should_stop() -> bool:
        """Return True if the loop should stop due to time limit or stop event.

        Returns:
            True if time limit exceeded or stop_event is set.
        """
        return _time_limit_exceeded() or bool(stop_event and stop_event.is_set())

    def _drain_engine_queue(engine: str) -> None:
        """Process all available jobs for one engine until queue empty or stopped.

        Args:
            engine: Engine name ('stockfish' or 'lc0') to drain.
        """
        while True:
            if _should_stop():
                break

            _send_heartbeat(engine)

            try:
                jobs = client.checkout(
                    engine=engine,
                    worker_id=worker_id,
                    batch_size=batch_size if not game_id else 1,
                    game_id=game_id,
                    dispatch_mode="pull",
                )
            except WorkerClientError as exc:
                log.error("Checkout failed for %s: %s", engine, exc)
                break

            if not jobs:
                break

            log.info("Claimed %d %s job(s): %s",
                     len(jobs), engine, ", ".join(str(j.id) for j in jobs))
            if on_jobs_claimed:
                on_jobs_claimed(jobs)

            for job in jobs:
                if stop_event and stop_event.is_set():
                    break
                if on_job_start:
                    on_job_start(job)
                job_start = time.monotonic()
                success = run_one_job(
                    job=job,
                    settings=settings,
                    stats=stats,
                    client=client,
                    progress_callback=on_progress,
                )
                if on_job_done:
                    on_job_done(job, success, time.monotonic() - job_start)

    for engine in engines:
        if _should_stop():
            break
        _drain_engine_queue(engine)

    return stats
