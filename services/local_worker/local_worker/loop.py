"""
Title: loop.py — Claim-analyse-submit worker loop with stats tracking
Description:
    Implements the main processing loop: checks out jobs from the API,
    dispatches to the appropriate engine analyser, submits results, and
    sends periodic heartbeats. Tracks per-session statistics.

Changelog:
    2026-05-09: Initial creation
    2026-05-13: Wired the persistent eval cache into the Stockfish branch
                (issue #67, builds on #65). Renamed the on-disk file from
                lc0_eval_cache.sqlite to eval_cache.sqlite and migrate the
                old name on first open if present.
    2026-05-14: Heartbeat status_message now includes avg seconds/game and
                cache hit-rate (issue #85). ``WorkerStats`` accumulates
                cache hits/lookups across per-job cache lifetimes via the
                new ``record_cache`` method.
"""
from __future__ import annotations

import logging
import os
import socket
import time
from dataclasses import dataclass
from typing import Callable, Optional

import chess.engine

from local_worker.worker_client import WorkerClient, WorkerClientError
from local_worker.analysis.stockfish import analyze_pgn as sf_analyze, build_stockfish_payload
from local_worker.analysis.lc0 import (
    analyze_pgn as lc0_analyze,
    build_lc0_payload,
    launch_engine as lc0_launch_engine,
)
from local_worker.analysis.eval_cache import EvalCache
from local_worker._shared import data_dir
from local_worker.config import Settings

log = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 30.0


def build_heartbeat_status(stats: "WorkerStats") -> str:
    """Render the worker-heartbeat ``status_message`` from session stats.

    The base form is ``processed=N``. When at least one game has been
    processed, an ``avg_s=<seconds>`` field is appended (1 decimal place).
    When the eval cache has served at least one lookup so far in this
    session, a ``cache_hits=<percent>%`` field is appended (rounded to
    the nearest whole percent). Fields are space-separated so the
    message stays short enough for the server-side status column
    (issue #85).

    Args:
        stats: Live ``WorkerStats`` for the current session.

    Returns:
        The fully rendered status message string.
    """
    parts = [f"processed={stats.games_processed}"]
    if stats.games_processed > 0:
        parts.append(f"avg_s={stats.avg_seconds_per_game():.1f}")
    if stats.cache_lookups > 0:
        hit_percent = round(100.0 * stats.cache_hits / stats.cache_lookups)
        parts.append(f"cache_hits={hit_percent}%")
    return " ".join(parts)


@dataclass
class WorkerStats:
    """Tracks per-session analysis statistics."""

    games_processed: int = 0
    stockfish_count: int = 0
    lc0_count: int = 0
    total_seconds: float = 0.0
    errors: int = 0
    cache_hits: int = 0
    cache_lookups: int = 0

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

    def record_cache(self, hits: int, lookups: int) -> None:
        """Add this job's cache hit/lookup counts to the session totals.

        The eval cache is opened per-job and closed at the end of each
        job. Call this from inside ``run_one_job`` just before
        ``cache.close()`` so the running totals stay accurate after the
        cache instance is gone (issue #85).

        Args:
            hits: Number of cache hits during the just-finished job.
            lookups: Total number of cache lookups (hits + misses)
                during the just-finished job.
        """
        self.cache_hits += int(hits)
        self.cache_lookups += int(lookups)


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


def _open_eval_cache(settings: Settings) -> Optional[EvalCache]:
    """Construct the shared eval cache for this job, honoring config + env flag.

    Used by both the lc0 and Stockfish branches. Returns None when caching
    is disabled via ``settings.eval_cache_enabled`` or the
    ``WLW_NO_EVAL_CACHE=1`` env override. Errors opening the DB are
    swallowed (we never want cache failures to kill a job).

    On first call, migrates the legacy ``lc0_eval_cache.sqlite`` filename
    to ``eval_cache.sqlite`` (the cache now stores both engines, keyed by
    network/engine prefix — no row-level migration needed).

    Args:
        settings: Worker settings.

    Returns:
        EvalCache instance, or None when disabled.
    """
    if not settings.eval_cache_enabled:
        return None
    if os.environ.get("WLW_NO_EVAL_CACHE") == "1":
        return None
    try:
        cache_path = data_dir() / "eval_cache.sqlite"
        legacy_path = data_dir() / "lc0_eval_cache.sqlite"
        if legacy_path.exists() and not cache_path.exists():
            log.info(
                "eval_cache: migrating %s -> %s", legacy_path.name, cache_path.name,
            )
            legacy_path.rename(cache_path)
        return EvalCache(cache_path)
    except Exception:
        log.warning("eval_cache: failed to open; running without cache", exc_info=True)
        return None


def run_one_job(
    *,
    job,
    settings: Settings,
    stats: WorkerStats,
    client: WorkerClient,
    progress_callback: Optional[Callable[..., None]] = None,
    lc0_engine: Optional[chess.engine.SimpleEngine] = None,
    lc0_network_name: str = "",
) -> bool:
    """Claim, analyse, and submit a single job.

    Args:
        job: Job dataclass from WorkerClient.checkout().
        settings: Current worker settings.
        stats: WorkerStats to update on completion.
        client: Authenticated WorkerClient for API calls.
        progress_callback: Optional callable(ply, total_plies) for per-move progress.
        lc0_engine: Optional warm lc0 engine to reuse for this job instead
            of cold-starting a new process. The caller (the batch drain
            loop) owns the engine's lifecycle. Saves ~6 s of weights +
            CUDA backend reload per game (issue #117).
        lc0_network_name: Resolved network name from the warm engine's
            ``id name``. Only consulted when ``lc0_engine`` is supplied.

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
    def _logging_progress(
        ply: int, total: int, san: str = "", fen: str = "", **extras
    ) -> None:
        log.info(
            "  job %s — move %d/%d %s",
            job.id, ply, total, san or "?",
        )
        if progress_callback:
            progress_callback(ply, total, san, fen, **extras)

    try:
        if job.engine == "stockfish":
            cache = _open_eval_cache(settings)
            try:
                result = sf_analyze(
                    pgn_text=job.pgn,
                    stockfish_path=settings.stockfish_path,
                    depth=settings.stockfish_depth,
                    threads=settings.stockfish_threads,
                    hash_mb=settings.stockfish_hash_mb,
                    syzygy_path=settings.syzygy_path,
                    progress_callback=_logging_progress,
                    eval_cache=cache,
                )
            finally:
                if cache is not None:
                    stats.record_cache(cache.hits, cache.lookups)
                    cache.prune(settings.eval_cache_max_mb * 1024 * 1024)
                    cache.close()
            payload = build_stockfish_payload(result, worker_id=worker_id)
            client.complete_stockfish(job_id=job.id, worker_id=worker_id, payload=payload)
        elif job.engine == "lc0":
            # The server currently encodes the lc0 node budget into the
            # ``depth`` field (e.g. depth=25000 nodes=None). Honour
            # ``job.depth`` as a fallback so we run at the requested
            # strength instead of silently defaulting to lc0_nodes
            # (issue #111).
            nodes = job.nodes or job.depth or settings.lc0_nodes
            cache = _open_eval_cache(settings)
            try:
                result = lc0_analyze(
                    pgn_text=job.pgn,
                    lc0_path=settings.lc0_path,
                    nodes=nodes,
                    weights_path=settings.lc0_weights_path,
                    syzygy_path=settings.syzygy_path,
                    backend=settings.lc0_backend or "cpu",
                    progress_callback=_logging_progress,
                    eval_cache=cache,
                    engine=lc0_engine,
                    network_name_override=lc0_network_name,
                )
            finally:
                if cache is not None:
                    stats.record_cache(cache.hits, cache.lookups)
                    cache.prune(settings.eval_cache_max_mb * 1024 * 1024)
                    cache.close()
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
    max_jobs: Optional[int] = None,
    batch_time_minutes: Optional[int] = None,
    game_id: Optional[str] = None,
    on_job_start: Optional[Callable] = None,
    on_job_done: Optional[Callable] = None,
    on_progress: Optional[Callable[..., None]] = None,
    on_jobs_claimed: Optional[Callable[[list], None]] = None,
    stop_event=None,
    _client=None,
) -> WorkerStats:
    """Run the main claim->analyse->submit loop.

    Claims jobs one at a time, launches the warm lc0 engine once per engine
    run, and stops on max_jobs / batch_time_minutes / stop_event / queue-empty
    — whichever fires first.

    Args:
        settings: Worker settings (API URL, key, engine paths, etc.).
        engines: List of engines to claim jobs for, e.g. ['stockfish', 'lc0'].
        max_jobs: Stop after this many completed jobs. None = until queue empty.
        batch_time_minutes: If set, stop after this many minutes.
        game_id: If set, request a specific game (single checkout).
        on_job_start: Optional callable(job) called before analysis.
        on_job_done: Optional callable(job, success, elapsed) called after.
        on_progress: Optional callable(ply, total_plies) for per-move progress.
        on_jobs_claimed: Optional callable([job]) called after each checkout.
        stop_event: Optional threading.Event; loop exits when set.
        _client: Optional pre-built WorkerClient for testing. When None, a
            real WorkerClient is created from settings.

    Returns:
        WorkerStats with totals for the run.
    """
    client = _client if _client is not None else WorkerClient(
        base_url=settings.api_url, api_key=settings.api_key
    )
    stats = WorkerStats()
    processed = 0
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
                    status_message=build_heartbeat_status(stats),
                )
            except WorkerClientError:
                pass
            last_heartbeat = now

    def _engine_alive(eng: chess.engine.SimpleEngine) -> bool:
        """Return True when the underlying lc0 process is still running.

        SimpleEngine exposes its protocol via ``.protocol``; the spawned
        subprocess sits under ``.transport``. ``returncode is None`` is
        the canonical "still running" signal for asyncio subprocess
        transports.
        """
        try:
            transport = getattr(eng, "transport", None)
            if transport is None:
                return True
            return transport.get_returncode() is None
        except Exception:  # noqa: BLE001
            return False

    def _should_stop() -> bool:
        """Return True if the loop should stop due to time limit or stop event.

        Returns:
            True if time limit exceeded or stop_event is set.
        """
        return _time_limit_exceeded() or bool(stop_event and stop_event.is_set())

    def _cap_reached() -> bool:
        """True once the optional max_jobs run cap is hit."""
        return max_jobs is not None and processed >= max_jobs

    def _drain_engine_queue(engine: str) -> None:
        """Claim one job at a time for `engine`, analyse+submit, until the
        queue is empty / max_jobs / batch_time / stop_event — whichever
        first. The warm lc0 engine (issue #117) is launched once for the
        whole engine run and quit on exit; a dead engine is relaunched by
        the existing _engine_alive guard inside the loop.

        Args:
            engine: Engine name ('stockfish' or 'lc0') to drain.
        """
        nonlocal processed
        warm_engine: Optional[chess.engine.SimpleEngine] = None
        warm_network_name = ""
        if engine == "lc0":
            try:
                warm_engine, warm_network_name = lc0_launch_engine(
                    lc0_path=settings.lc0_path,
                    weights_path=settings.lc0_weights_path,
                    syzygy_path=settings.syzygy_path,
                    backend=settings.lc0_backend or "cpu",
                )
            except Exception:  # noqa: BLE001
                log.warning("lc0: warm engine launch failed; per-job cold-start", exc_info=True)
                warm_engine = None
        try:
            while True:
                if _should_stop() or _cap_reached():
                    break
                _send_heartbeat(engine)
                try:
                    jobs = client.checkout(
                        engine=engine,
                        worker_id=worker_id,
                        batch_size=1,
                        game_id=game_id,
                        dispatch_mode="pull",
                    )
                except WorkerClientError as exc:
                    log.error("Checkout failed for %s: %s", engine, exc)
                    break
                if not jobs:
                    break
                job = jobs[0]
                if on_jobs_claimed:
                    on_jobs_claimed([job])
                if on_job_start:
                    on_job_start(job)
                job_start = time.monotonic()
                success = run_one_job(
                    job=job,
                    settings=settings,
                    stats=stats,
                    client=client,
                    progress_callback=on_progress,
                    lc0_engine=warm_engine if engine == "lc0" else None,
                    lc0_network_name=warm_network_name,
                )
                processed += 1
                if (
                    engine == "lc0"
                    and warm_engine is not None
                    and not _engine_alive(warm_engine)
                ):
                    log.warning("lc0: warm engine died; relaunching")
                    try:
                        warm_engine, warm_network_name = lc0_launch_engine(
                            lc0_path=settings.lc0_path,
                            weights_path=settings.lc0_weights_path,
                            syzygy_path=settings.syzygy_path,
                            backend=settings.lc0_backend or "cpu",
                        )
                    except Exception:  # noqa: BLE001
                        log.warning("lc0: relaunch failed; remaining jobs cold-start", exc_info=True)
                        warm_engine = None
                        warm_network_name = ""
                if on_job_done:
                    on_job_done(job, success, time.monotonic() - job_start)
        finally:
            if warm_engine is not None:
                try:
                    warm_engine.quit()
                except Exception:  # noqa: BLE001
                    log.warning("lc0: warm engine quit failed", exc_info=True)

    for engine in engines:
        if _should_stop() or _cap_reached():
            break
        _drain_engine_queue(engine)

    return stats
