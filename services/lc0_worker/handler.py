"""RunPod Serverless handler for Lc0 analysis."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone

import runpod
import sqlalchemy.exc
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from lc0_worker.services.lc0_service import analyze_pgn
from lc0_worker.storage.models import (
    AnalysisJob,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    SystemEvent,
)

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
DATABASE_URL: str = os.environ["DATABASE_URL"]
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif (
    DATABASE_URL.startswith("postgresql://")
    and "+" not in DATABASE_URL.split("://", 1)[0]
):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

from lc0_worker.storage.migrate_add_pv_continuations import migrate_add_pv_continuations
migrate_add_pv_continuations(_engine)


def _write_system_event(
    session,
    *,
    status: str,
    started_at: datetime,
    duration_seconds: float,
    game_id: str,
    runpod_job_id: str,
    details: dict | None = None,
    error_message: str | None = None,
) -> None:
    event = SystemEvent(
        event_type="lc0",
        status=status,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        duration_seconds=duration_seconds,
        details=json.dumps(
            {
                "game_id": game_id,
                "runpod_job_id": runpod_job_id,
                **(details or {}),
            }
        ),
        error_message=error_message,
    )
    session.add(event)


def _log_startup_diagnostics() -> None:
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
    if gpu_lines:
        for index, line in enumerate(gpu_lines, start=1):
            log.info("Lc0 startup: gpu[%d]=%s", index, line)
    else:
        log.warning("Lc0 startup: nvidia-smi returned no GPU information")


def _save_analysis(session, game_id: str, result) -> None:
    lga = session.execute(
        select(Lc0GameAnalysis).where(Lc0GameAnalysis.game_id == game_id)
    ).scalar_one_or_none()

    if lga is None:
        lga = Lc0GameAnalysis(game_id=game_id)
        session.add(lga)
        session.flush()

    lga.analyzed_at = result.analyzed_at
    lga.engine_nodes = result.engine_nodes
    lga.network_name = result.network_name
    lga.white_win_prob = result.white_stats.avg_win_prob
    lga.white_draw_prob = result.white_stats.avg_draw_prob
    lga.white_loss_prob = result.white_stats.avg_loss_prob
    lga.black_win_prob = result.black_stats.avg_win_prob
    lga.black_draw_prob = result.black_stats.avg_draw_prob
    lga.black_loss_prob = result.black_stats.avg_loss_prob
    lga.white_blunders = result.white_stats.blunders
    lga.white_mistakes = result.white_stats.mistakes
    lga.white_inaccuracies = result.white_stats.inaccuracies
    lga.black_blunders = result.black_stats.blunders
    lga.black_mistakes = result.black_stats.mistakes
    lga.black_inaccuracies = result.black_stats.inaccuracies

    for old in list(lga.moves):
        session.delete(old)
    session.flush()

    for mr in result.moves:
        session.add(
            Lc0MoveAnalysis(
                analysis_id=lga.id,
                ply=mr.ply,
                san=mr.san,
                fen=mr.fen,
                wdl_win=mr.wdl_win,
                wdl_draw=mr.wdl_draw,
                wdl_loss=mr.wdl_loss,
                cp_equiv=mr.cp_equiv,
                best_move=mr.best_move,
                arrow_uci=mr.arrow_uci,
                arrow_uci_2=mr.arrow_uci_2,
                arrow_uci_3=mr.arrow_uci_3,
                arrow_score_1=mr.arrow_score_1,
                arrow_score_2=mr.arrow_score_2,
                arrow_score_3=mr.arrow_score_3,
                move_win_delta=mr.move_win_delta,
                classification=mr.classification,
                pv_san_1=json.dumps(mr.pv_san_1) if mr.pv_san_1 else None,
                pv_san_2=json.dumps(mr.pv_san_2) if mr.pv_san_2 else None,
                pv_san_3=json.dumps(mr.pv_san_3) if mr.pv_san_3 else None,
            )
        )


def _mark_job_completed(session, game_id: str, runpod_job_id: str) -> None:
    job = session.execute(
        select(AnalysisJob).where(
            AnalysisJob.game_id == game_id,
            AnalysisJob.engine == "lc0",
            AnalysisJob.runpod_job_id == runpod_job_id,
        )
    ).scalar_one_or_none()

    if job:
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        if job.submitted_at:
            elapsed = job.completed_at - job.submitted_at.replace(tzinfo=timezone.utc)
            job.duration_seconds = elapsed.total_seconds()


def handler(job: dict) -> dict:
    job_input = job["input"]
    game_id: str = job_input["game_id"]
    pgn_string: str = job_input["pgn"]
    nodes: int = int(job_input.get("nodes", LC0_NODES))
    weights_path: str = str(job_input.get("weights_path", LC0_NETWORK))
    runpod_job_id: str = job.get("id", "")
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()

    log.info(
        "Starting Lc0 analysis: game_id=%s nodes=%d syzygy=%s",
        game_id,
        nodes,
        LC0_SYZYGY_PATH,
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
        log.error("Analysis failed for game_id=%s: %s", game_id, exc, exc_info=True)
        duration_seconds = time.perf_counter() - started_clock
        with _SessionLocal() as session:
            _write_system_event(
                session,
                status="failed",
                started_at=started_at,
                duration_seconds=duration_seconds,
                game_id=game_id,
                runpod_job_id=runpod_job_id,
                error_message=str(exc),
            )
            session.commit()
        return {"game_id": game_id, "status": "error", "error": str(exc)}

    try:
        with _SessionLocal() as session:
            _save_analysis(session, game_id, result)
            _mark_job_completed(session, game_id, runpod_job_id)
            duration_seconds = time.perf_counter() - started_clock
            _write_system_event(
                session,
                status="completed",
                started_at=started_at,
                duration_seconds=duration_seconds,
                game_id=game_id,
                runpod_job_id=runpod_job_id,
                details={
                    "moves_analysed": len(result.moves),
                    "white_win_prob": result.white_stats.avg_win_prob,
                    "black_win_prob": result.black_stats.avg_win_prob,
                },
            )
            session.commit()
    except sqlalchemy.exc.OperationalError:
        raise
    except Exception as exc:
        log.error("DB write failed for game_id=%s: %s", game_id, exc, exc_info=True)
        duration_seconds = time.perf_counter() - started_clock
        with _SessionLocal() as session:
            _write_system_event(
                session,
                status="failed",
                started_at=started_at,
                duration_seconds=duration_seconds,
                game_id=game_id,
                runpod_job_id=runpod_job_id,
                error_message=str(exc),
            )
            session.commit()
        return {"game_id": game_id, "status": "error", "error": str(exc)}

    log.info(
        "Completed Lc0 analysis: game_id=%s moves=%d W-win=%.1f B-win=%.1f",
        game_id,
        len(result.moves),
        result.white_stats.avg_win_prob,
        result.black_stats.avg_win_prob,
    )

    return {
        "game_id": game_id,
        "moves_analysed": len(result.moves),
        "white_win_prob": result.white_stats.avg_win_prob,
        "black_win_prob": result.black_stats.avg_win_prob,
        "status": "ok",
    }


_log_startup_diagnostics()

runpod.serverless.start({"handler": handler})
