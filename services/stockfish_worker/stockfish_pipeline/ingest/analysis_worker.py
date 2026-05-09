"""
Title: analysis_worker.py — Stockfish analysis job worker
Description:
    Pulls pending Stockfish analysis jobs from the Django API via WorkerClient
    and runs Stockfish analysis on each game's PGN. All job claiming, result
    submission, and failure reporting go through HTTP — no direct DB access.

Changelog:
    2026-05-08 (#1): Rewrite to use WorkerClient instead of SQLAlchemy
"""
from __future__ import annotations

import logging
import os
import platform
import socket
import sys
import time

from stockfish_pipeline.services.stockfish_service import analyze_pgn
from wood_league_shared.worker_client import WorkerClient

log = logging.getLogger(__name__)

_WORKER_ID = socket.gethostname()
_IS_TTY = sys.stdout.isatty()


def _collect_worker_info(stockfish_path: str) -> dict:
    """Collect CPU model, core count, total RAM, and Stockfish binary path.

    Args:
        stockfish_path: Resolved path to the Stockfish binary.

    Returns:
        Dict with keys: cpu_model, cpu_cores, memory_mb, stockfish_binary.
    """
    cpu_model: str | None = None
    cpu_cores: int | None = None
    memory_mb: int | None = None

    try:
        cpu_cores = os.cpu_count()
    except Exception:
        pass

    try:
        if platform.system() == "Linux":
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        cpu_model = line.split(":", 1)[1].strip()
                        break
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        memory_mb = int(line.split()[1]) // 1024
                        break
        elif platform.system() == "Darwin":
            import subprocess
            cpu_model = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
            mem_bytes = int(subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True
            ).strip())
            memory_mb = mem_bytes // (1024 * 1024)
    except Exception:
        pass

    return {
        "cpu_model": cpu_model,
        "cpu_cores": cpu_cores,
        "memory_mb": memory_mb,
        "stockfish_binary": stockfish_path,
    }


def _build_complete_payload(result) -> dict:
    """Build the StockfishCompleteSerializer payload dict from a GameResult.

    Args:
        result: GameResult returned by analyze_pgn().

    Returns:
        Dict matching StockfishCompleteSerializer's expected fields.
    """
    return {
        'engine_depth': result.engine_depth,
        'white_accuracy': result.white_stats.accuracy,
        'black_accuracy': result.black_stats.accuracy,
        'white_acpl': result.white_stats.acpl,
        'black_acpl': result.black_stats.acpl,
        'white_blunders': result.white_stats.blunders,
        'white_mistakes': result.white_stats.mistakes,
        'white_inaccuracies': result.white_stats.inaccuracies,
        'black_blunders': result.black_stats.blunders,
        'black_mistakes': result.black_stats.mistakes,
        'black_inaccuracies': result.black_stats.inaccuracies,
        'moves': [
            {
                'ply': mr.ply,
                'san': mr.san,
                'fen': mr.fen,
                'cp_eval': int(mr.cp_eval),
                'cpl': int(mr.cpl),
                'best_move': mr.best_move,
                'classification': mr.classification.capitalize(),
            }
            for mr in result.moves
        ],
    }


def _run_one_job(
    client: WorkerClient,
    job,
    stockfish_path: str,
    depth: int,
    threads: int,
    hash_mb: int,
) -> None:
    """Analyze a single job and report completion via the API.

    Args:
        client: Authenticated WorkerClient instance.
        job: Job dataclass from checkout().
        stockfish_path: Resolved path to the Stockfish binary.
        depth: Stockfish analysis depth.
        threads: Stockfish thread count.
        hash_mb: Stockfish hash table size in MB.

    Raises:
        ValueError: If the job has no PGN.
        Any exception from analyze_pgn or complete_stockfish is propagated.
    """
    if not job.pgn:
        raise ValueError("Job has no PGN")

    result = analyze_pgn(
        job.pgn,
        stockfish_path=stockfish_path,
        depth=depth,
        threads=threads,
        hash_mb=hash_mb,
    )
    payload = _build_complete_payload(result)
    client.complete_stockfish(job_id=job.id, worker_id=_WORKER_ID, payload=payload)
    log.info(
        "Completed job %d  game=%s  W=%.1f%%  B=%.1f%%",
        job.id, job.game_id,
        result.white_stats.accuracy, result.black_stats.accuracy,
    )


def run_worker(
    stockfish_path: str,
    *,
    api_url: str,
    api_key: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
    poll_interval: float = 5.0,
    limit: int | None = None,
) -> None:
    """Main worker loop. Polls the Django API for Stockfish jobs and processes them.

    Args:
        stockfish_path: Resolved path to the Stockfish binary.
        api_url: Base URL of the Django API, e.g. 'https://app.example.com'.
        api_key: Raw API key for X-Api-Key authentication.
        depth: Stockfish analysis depth (default 20).
        threads: Stockfish thread count per game (default 1).
        hash_mb: Stockfish hash table size in MB (default 256).
        poll_interval: Seconds to wait between polls when the queue is empty.
            Set to 0 to exit immediately when the queue is empty.
        limit: Stop after processing this many games (None = unlimited).
    """
    client = WorkerClient(base_url=api_url, api_key=api_key)
    worker_info = _collect_worker_info(stockfish_path)

    log.info(
        "Worker starting. stockfish=%s depth=%d threads=%d hash=%dMB "
        "cpu=%s cores=%s ram=%sMB limit=%s",
        stockfish_path, depth, threads, hash_mb,
        worker_info.get("cpu_model", "unknown"),
        worker_info.get("cpu_cores"),
        worker_info.get("memory_mb"),
        limit or "∞",
    )

    processed = 0
    failed = 0

    client.heartbeat(worker_id=_WORKER_ID, engine='stockfish', status_message='starting')

    try:
        while limit is None or processed < limit:
            jobs = client.checkout(engine='stockfish', worker_id=_WORKER_ID)

            if not jobs:
                client.heartbeat(worker_id=_WORKER_ID, engine='stockfish', status_message='idle')
                if poll_interval <= 0:
                    break
                time.sleep(poll_interval)
                continue

            job = jobs[0]
            client.heartbeat(
                worker_id=_WORKER_ID,
                engine='stockfish',
                status_message=f'analyzing {job.game_id}',
            )
            try:
                _run_one_job(client, job, stockfish_path, depth, threads, hash_mb)
                processed += 1
            except Exception as exc:
                failed += 1
                log.exception("Job %d FAILED (game=%s): %s", job.id, job.game_id, exc)
                client.fail(job_id=job.id, worker_id=_WORKER_ID, error=str(exc))
                client.heartbeat(
                    worker_id=_WORKER_ID,
                    engine='stockfish',
                    status_message=f'error on {job.game_id}',
                )

    finally:
        client.heartbeat(worker_id=_WORKER_ID, engine='stockfish', status_message='stopped')

    log.info("Done. Processed %d game(s), %d failed.", processed, failed)
