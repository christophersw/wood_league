"""
Title: handler.py — RunPod serverless Lc0 analysis handler
Description:
    RunPod serverless worker that receives job_id + PGN strings, runs Lc0
    analysis, and reports results to the Django API via WorkerClient.
    No direct database access — all persistence goes through the HTTP API.

Changelog:
    2026-05-08 (#1): Replace SQLAlchemy with WorkerClient HTTP API
"""
from __future__ import annotations

import json
import logging
import os
import subprocess

import runpod

from lc0_worker.services.lc0_service import analyze_pgn
from wood_league_shared.worker_client import WorkerClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

LC0_PATH: str = os.environ.get("LC0_PATH", "/usr/local/bin/lc0")
LC0_NODES: int = int(os.environ.get("LC0_NODES", "25000"))
LC0_NETWORK: str = os.environ.get("LC0_NETWORK", "")
LC0_SYZYGY_PATH: str = os.environ.get("LC0_SYZYGY_PATH", "/runpod-volume/syzygy")
LC0_BACKEND: str = os.environ.get("LC0_BACKEND", "cudnn-fp16")
WORKER_API_URL: str = os.environ["WORKER_API_URL"]
WORKER_API_KEY: str = os.environ["WORKER_API_KEY"]
_WORKER_ID: str = "runpod-lc0"

# Module-level client — reused across warm RunPod calls for connection pooling
_client = WorkerClient(base_url=WORKER_API_URL, api_key=WORKER_API_KEY)


def _log_startup_diagnostics() -> None:
    """Log GPU information at startup for observability."""
    log.info(
        "Lc0 startup: path=%s backend=%s network=%s syzygy=%s",
        LC0_PATH,
        LC0_BACKEND,
        LC0_NETWORK or "<default>",
        LC0_SYZYGY_PATH,
    )
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,cuda_version",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        log.warning("Lc0 startup: nvidia-smi not found; unable to report CUDA runtime")
        return
    except subprocess.SubprocessError as exc:
        log.warning("Lc0 startup: failed to query CUDA runtime via nvidia-smi: %s", exc)
        return

    gpu_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for index, line in enumerate(gpu_lines, start=1):
        log.info("Lc0 startup: gpu[%d]=%s", index, line)
    if not gpu_lines:
        log.warning("Lc0 startup: nvidia-smi returned no GPU information")


def _build_complete_payload(result) -> dict:
    """Build the Lc0CompleteSerializer payload dict from an Lc0GameResult.

    Args:
        result: Lc0GameResult returned by analyze_pgn().

    Returns:
        Dict matching Lc0CompleteSerializer's expected fields.
    """
    return {
        'engine_nodes': result.engine_nodes,
        'network_name': result.network_name,
        'white_win_prob': result.white_stats.avg_win_prob,
        'white_draw_prob': result.white_stats.avg_draw_prob,
        'white_loss_prob': result.white_stats.avg_loss_prob,
        'black_win_prob': result.black_stats.avg_win_prob,
        'black_draw_prob': result.black_stats.avg_draw_prob,
        'black_loss_prob': result.black_stats.avg_loss_prob,
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
                'wdl_win': mr.wdl_win,
                'wdl_draw': mr.wdl_draw,
                'wdl_loss': mr.wdl_loss,
                'cp_equiv': mr.cp_equiv,
                'best_move': mr.best_move,
                'arrow_uci': mr.arrow_uci,
                'arrow_uci_2': mr.arrow_uci_2,
                'arrow_uci_3': mr.arrow_uci_3,
                'arrow_score_1': mr.arrow_score_1,
                'arrow_score_2': mr.arrow_score_2,
                'arrow_score_3': mr.arrow_score_3,
                'move_win_delta': mr.move_win_delta,
                'classification': mr.classification.capitalize(),
                'pv_san_1': json.dumps(mr.pv_san_1) if mr.pv_san_1 else None,
                'pv_san_2': json.dumps(mr.pv_san_2) if mr.pv_san_2 else None,
                'pv_san_3': json.dumps(mr.pv_san_3) if mr.pv_san_3 else None,
            }
            for mr in result.moves
        ],
    }


def handler(job: dict) -> dict:
    """RunPod job handler — called once per job by the RunPod SDK.

    Expects job["input"] to contain:
        job_id (int): Django AnalysisJob.id — set by the dispatcher at submission.
        pgn (str): PGN text to analyze.
        nodes (int, optional): Node budget (default LC0_NODES).
        weights_path (str, optional): Path to network weights (default LC0_NETWORK).

    Returns:
        Dict with job_id and status ('ok' or 'error').
    """
    job_input = job["input"]
    job_id: int = int(job_input["job_id"])
    pgn_string: str = job_input["pgn"]
    nodes: int = int(job_input.get("nodes", LC0_NODES))
    weights_path: str = str(job_input.get("weights_path", LC0_NETWORK))

    log.info(
        "Starting Lc0 analysis: job_id=%d nodes=%d syzygy=%s",
        job_id, nodes, LC0_SYZYGY_PATH,
    )

    try:
        result = analyze_pgn(
            pgn_text=pgn_string,
            lc0_path=LC0_PATH,
            nodes=nodes,
            weights_path=weights_path,
            syzygy_path=LC0_SYZYGY_PATH,
            backend=LC0_BACKEND,
        )
    except Exception as exc:
        log.error("Analysis failed for job_id=%d: %s", job_id, exc, exc_info=True)
        _client.fail(job_id=job_id, worker_id=_WORKER_ID, error=str(exc))
        return {"job_id": job_id, "status": "error", "error": str(exc)}

    payload = _build_complete_payload(result)
    _client.complete_lc0(job_id=job_id, worker_id=_WORKER_ID, payload=payload)

    log.info(
        "Completed Lc0 analysis: job_id=%d moves=%d W-win=%.1f B-win=%.1f",
        job_id, len(result.moves),
        result.white_stats.avg_win_prob, result.black_stats.avg_win_prob,
    )
    return {
        "job_id": job_id,
        "moves_analysed": len(result.moves),
        "white_win_prob": result.white_stats.avg_win_prob,
        "black_win_prob": result.black_stats.avg_win_prob,
        "status": "ok",
    }


_log_startup_diagnostics()

runpod.serverless.start({"handler": handler})
