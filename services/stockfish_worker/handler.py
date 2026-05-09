"""
Title: handler.py — RunPod serverless Stockfish analysis handler
Description:
    RunPod serverless worker that receives job_id + PGN strings, runs Stockfish
    analysis, and reports results to the Django API via WorkerClient.
    No direct database access — all persistence goes through the HTTP API.

Changelog:
    2026-05-08 (#1): Replace SQLAlchemy with WorkerClient HTTP API
"""
from __future__ import annotations

import logging
import os

import runpod

from stockfish_pipeline.services.stockfish_service import analyze_pgn
from wood_league_shared.worker_client import WorkerClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

STOCKFISH_PATH: str = os.environ.get("STOCKFISH_PATH", "/usr/games/stockfish")
ANALYSIS_DEPTH: int = int(os.environ.get("ANALYSIS_DEPTH", "20"))
ANALYSIS_THREADS: int = int(os.environ.get("ANALYSIS_THREADS", "8"))
ANALYSIS_HASH_MB: int = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))
SYZYGY_PATH: str = os.environ.get("SYZYGY_PATH", "/runpod-volume/syzygy")
WORKER_API_URL: str = os.environ["WORKER_API_URL"]
WORKER_API_KEY: str = os.environ["WORKER_API_KEY"]
_WORKER_ID: str = "runpod-stockfish"

# Module-level client — reused across warm RunPod calls for connection pooling
_client = WorkerClient(base_url=WORKER_API_URL, api_key=WORKER_API_KEY)


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


def handler(job: dict) -> dict:
    """RunPod job handler — called once per job by the RunPod SDK.

    Expects job["input"] to contain:
        job_id (int): Django AnalysisJob.id — set by the dispatcher at submission.
        pgn (str): PGN text to analyze.
        depth (int, optional): Analysis depth (default ANALYSIS_DEPTH).
        threads (int, optional): Engine threads (default ANALYSIS_THREADS).
        hash_mb (int, optional): Hash table size in MB (default ANALYSIS_HASH_MB).

    Returns:
        Dict with job_id and status ('ok' or 'error').
    """
    job_input = job["input"]
    job_id: int = int(job_input["job_id"])
    pgn_string: str = job_input["pgn"]
    depth: int = int(job_input.get("depth", ANALYSIS_DEPTH))
    threads: int = int(job_input.get("threads", ANALYSIS_THREADS))
    hash_mb: int = int(job_input.get("hash_mb", ANALYSIS_HASH_MB))

    log.info(
        "Starting analysis: job_id=%d depth=%d threads=%d hash_mb=%d syzygy=%s",
        job_id, depth, threads, hash_mb, SYZYGY_PATH,
    )

    try:
        result = analyze_pgn(
            pgn_text=pgn_string,
            stockfish_path=STOCKFISH_PATH,
            depth=depth,
            threads=threads,
            hash_mb=hash_mb,
            syzygy_path=SYZYGY_PATH,
        )
    except Exception as exc:
        log.error("Analysis failed for job_id=%d: %s", job_id, exc, exc_info=True)
        _client.fail(job_id=job_id, worker_id=_WORKER_ID, error=str(exc))
        return {"job_id": job_id, "status": "error", "error": str(exc)}

    payload = _build_complete_payload(result)
    _client.complete_stockfish(job_id=job_id, worker_id=_WORKER_ID, payload=payload)

    log.info(
        "Completed: job_id=%d moves=%d W=%.1f%% B=%.1f%%",
        job_id, len(result.moves),
        result.white_stats.accuracy, result.black_stats.accuracy,
    )
    return {
        "job_id": job_id,
        "moves_analyzed": len(result.moves),
        "accuracy_white": result.white_stats.accuracy,
        "accuracy_black": result.black_stats.accuracy,
        "status": "ok",
    }


runpod.serverless.start({"handler": handler})
