from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone

import runpod
from sqlalchemy import and_, select

from wood_league_shared.storage.database import get_session, init_db
from wood_league_shared.ingest.sync_service import ChessComSyncService
from wood_league_shared.storage.models import AnalysisJob, Game, SystemEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dispatchers")


def _log_system_event(
    event_type: str,
    status: str,
    details: dict | None = None,
    error_message: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Log a system event to the database.
    
    Args:
        event_type: Type of event (e.g., "ingest", "stockfish", "lc0")
        status: Event status ("started", "completed", "failed")
        details: Optional dict with event-specific metadata
        error_message: Optional error message if status is "failed"
        duration_seconds: Duration of the event if completed
    """
    try:
        with get_session() as session:
            event = SystemEvent(
                event_type=event_type,
                status=status,
                details=json.dumps(details) if details else None,
                error_message=error_message,
                duration_seconds=duration_seconds,
            )
            if status in ("completed", "failed"):
                event.completed_at = datetime.now(timezone.utc)
            session.add(event)
            session.commit()
    except Exception as e:
        log.error("Failed to log system event: %s", e)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _endpoint_ids() -> tuple[str, str]:
    stockfish_endpoint = os.environ.get("RUNPOD_STOCKFISH_ENDPOINT_ID", "").strip()
    if not stockfish_endpoint:
        stockfish_endpoint = os.environ.get("RUNPOD_ENDPOINT_ID", "").strip()

    lc0_endpoint = os.environ.get("RUNPOD_LC0_ENDPOINT_ID", "").strip()

    if not stockfish_endpoint:
        raise RuntimeError("Set RUNPOD_STOCKFISH_ENDPOINT_ID (or RUNPOD_ENDPOINT_ID fallback)")
    if not lc0_endpoint:
        raise RuntimeError("Set RUNPOD_LC0_ENDPOINT_ID")

    return stockfish_endpoint, lc0_endpoint


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_usernames(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [u.strip().lower() for u in raw.split(",") if u.strip()]


def _load_pgn(game_id: str) -> str:
    with get_session() as session:
        game = session.get(Game, game_id)
        return game.pgn if game and game.pgn else ""


def _submit_engine_jobs(
    *,
    engine: str,
    endpoint,
    limit: int | None = None,
    stockfish_threads: int = 8,
    stockfish_hash_mb: int = 2048,
    lc0_nodes: int = 25000,
    lc0_network: str = "",
) -> int:
    stmt = (
        select(AnalysisJob)
        .where(
            and_(
                AnalysisJob.status == "pending",
                AnalysisJob.engine == engine,
            )
        )
        .order_by(AnalysisJob.priority.desc(), AnalysisJob.created_at)
    )
    if limit:
        stmt = stmt.limit(limit)

    submitted = 0
    with get_session() as session:
        jobs = session.execute(stmt).scalars().all()

        for job in jobs:
            pgn = _load_pgn(job.game_id)
            if not pgn:
                log.warning("%s game_id=%s has no PGN - skipping", engine, job.game_id)
                continue

            try:
                if engine == "stockfish":
                    payload = {
                        "game_id": job.game_id,
                        "pgn": pgn,
                        "depth": int(job.depth or 20),
                        "threads": stockfish_threads,
                        "hash_mb": stockfish_hash_mb,
                    }
                else:
                    payload = {
                        "game_id": job.game_id,
                        "pgn": pgn,
                        "nodes": int(job.depth or lc0_nodes),
                    }
                    if lc0_network:
                        payload["weights_path"] = lc0_network

                run_request = endpoint.run(payload)
                job.runpod_job_id = run_request.job_id
                job.submitted_at = datetime.now(timezone.utc)
                job.status = "submitted"
                submitted += 1
                log.info(
                    "Submitted %s game_id=%s -> runpod_job_id=%s",
                    engine,
                    job.game_id,
                    run_request.job_id,
                )
            except Exception:
                log.exception("Failed submitting %s game_id=%s", engine, job.game_id)

        session.commit()

    return submitted


def _enqueue_new_game_jobs(
    *,
    game_ids: list[str],
    queue_stockfish: bool,
    queue_lc0: bool,
    stockfish_depth: int,
    lc0_nodes: int,
) -> tuple[int, int]:
    if not game_ids or (not queue_stockfish and not queue_lc0):
        return 0, 0

    enqueued_sf = 0
    enqueued_lc0 = 0

    with get_session() as session:
        for game_id in game_ids:
            if queue_stockfish and _enqueue_job_if_needed(
                session=session,
                game_id=game_id,
                engine="stockfish",
                depth=stockfish_depth,
            ):
                enqueued_sf += 1

            if queue_lc0 and _enqueue_job_if_needed(
                session=session,
                game_id=game_id,
                engine="lc0",
                depth=lc0_nodes,
            ):
                enqueued_lc0 += 1

        session.commit()

    return enqueued_sf, enqueued_lc0


def _enqueue_job_if_needed(*, session, game_id: str, engine: str, depth: int) -> bool:
    existing_active = session.execute(
        select(AnalysisJob).where(
            and_(
                AnalysisJob.game_id == game_id,
                AnalysisJob.engine == engine,
                AnalysisJob.status.in_(["pending", "running", "submitted"]),
            )
        )
    ).scalar_one_or_none()
    if existing_active is not None:
        return False

    existing_complete = session.execute(
        select(AnalysisJob).where(
            and_(
                AnalysisJob.game_id == game_id,
                AnalysisJob.engine == engine,
                AnalysisJob.status == "completed",
                AnalysisJob.depth >= depth,
            )
        )
    ).scalar_one_or_none()
    if existing_complete is not None:
        return False

    session.add(
        AnalysisJob(
            game_id=game_id,
            engine=engine,
            depth=depth,
            status="pending",
            priority=10,
        )
    )
    return True


def _run_ingest_sweep(
    *,
    usernames: list[str],
    ingest_month_limit: int,
    chess_com_user_agent: str,
    queue_stockfish_after_ingest: bool,
    queue_lc0_after_ingest: bool,
    stockfish_depth: int,
    lc0_nodes: int,
) -> tuple[int, int, int, int, int]:
    if not usernames:
        return 0, 0, 0, 0, 0

    service = ChessComSyncService(
        ingest_month_limit=ingest_month_limit,
        user_agent=chess_com_user_agent,
    )
    results = service.sync_many(usernames)

    inserted = sum(r.inserted for r in results)
    updated = sum(r.updated for r in results)
    archives = sum(r.archives_scanned for r in results)
    inserted_game_ids: list[str] = []
    for result in results:
        inserted_game_ids.extend(result.inserted_game_ids)

    enqueued_sf, enqueued_lc0 = _enqueue_new_game_jobs(
        game_ids=inserted_game_ids,
        queue_stockfish=queue_stockfish_after_ingest,
        queue_lc0=queue_lc0_after_ingest,
        stockfish_depth=stockfish_depth,
        lc0_nodes=lc0_nodes,
    )

    return inserted, updated, archives, enqueued_sf, enqueued_lc0


def main() -> None:
    runpod.api_key = _required_env("RUNPOD_API_KEY")
    stockfish_endpoint_id, lc0_endpoint_id = _endpoint_ids()

    stockfish_endpoint = runpod.Endpoint(stockfish_endpoint_id)
    lc0_endpoint = runpod.Endpoint(lc0_endpoint_id)

    sf_poll_interval = int(os.environ.get("SF_POLL_INTERVAL", "60"))
    lc0_poll_interval = int(os.environ.get("LC0_POLL_INTERVAL", "60"))

    stockfish_threads = int(os.environ.get("ANALYSIS_THREADS", "8"))
    stockfish_hash_mb = int(os.environ.get("ANALYSIS_HASH_MB", "2048"))
    stockfish_depth = int(os.environ.get("ANALYSIS_DEPTH", "20"))
    lc0_nodes = int(os.environ.get("LC0_NODES", "25000"))
    lc0_network = os.environ.get("LC0_NETWORK", "")

    chess_usernames = _parse_usernames(os.environ.get("CHESS_COM_USERNAMES", ""))
    ingest_poll_interval = int(os.environ.get("INGEST_POLL_INTERVAL", "900"))
    ingest_month_limit = int(os.environ.get("INGEST_MONTH_LIMIT", "24"))
    chess_com_user_agent = os.environ.get(
        "CHESS_COM_USER_AGENT",
        "wood-league-dispatchers/0.1 (+runpod dispatcher)",
    )
    queue_stockfish_after_ingest = _parse_bool(
        os.environ.get("QUEUE_STOCKFISH_AFTER_INGEST"),
        default=True,
    )
    queue_lc0_after_ingest = _parse_bool(
        os.environ.get("QUEUE_LC0_AFTER_INGEST"),
        default=False,
    )

    init_db()

    log.info(
        "Dispatchers started: stockfish_endpoint=%s lc0_endpoint=%s",
        stockfish_endpoint_id,
        lc0_endpoint_id,
    )
    if chess_usernames:
        log.info(
            "Ingest enabled: usernames=%s interval=%ss queue_stockfish=%s queue_lc0=%s",
            ",".join(chess_usernames),
            ingest_poll_interval,
            queue_stockfish_after_ingest,
            queue_lc0_after_ingest,
        )
    else:
        log.info("Ingest disabled: CHESS_COM_USERNAMES is empty")

    last_sf = 0.0
    last_lc0 = 0.0
    last_ingest = 0.0

    while True:
        now = time.time()

        if chess_usernames and now - last_ingest >= ingest_poll_interval:
            ingest_start_time = time.time()
            _log_system_event("ingest", "started")
            try:
                inserted, updated, archives, enqueued_sf, enqueued_lc0 = _run_ingest_sweep(
                    usernames=chess_usernames,
                    ingest_month_limit=ingest_month_limit,
                    chess_com_user_agent=chess_com_user_agent,
                    queue_stockfish_after_ingest=queue_stockfish_after_ingest,
                    queue_lc0_after_ingest=queue_lc0_after_ingest,
                    stockfish_depth=stockfish_depth,
                    lc0_nodes=lc0_nodes,
                )
                duration = time.time() - ingest_start_time
                _log_system_event(
                    "ingest",
                    "completed",
                    details={
                        "archives_scanned": archives,
                        "inserted": inserted,
                        "updated": updated,
                        "enqueued_stockfish": enqueued_sf,
                        "enqueued_lc0": enqueued_lc0,
                    },
                    duration_seconds=duration,
                )
                log.info(
                    "Ingest sweep complete: archives=%d inserted=%d updated=%d enqueued_stockfish=%d enqueued_lc0=%d",
                    archives,
                    inserted,
                    updated,
                    enqueued_sf,
                    enqueued_lc0,
                )
            except Exception as e:
                duration = time.time() - ingest_start_time
                _log_system_event(
                    "ingest",
                    "failed",
                    error_message=str(e),
                    duration_seconds=duration,
                )
                log.exception("Chess.com ingest sweep failed")
            last_ingest = now

        if now - last_sf >= sf_poll_interval:
            sf_start_time = time.time()
            _log_system_event("stockfish_dispatch", "started")
            try:
                n = _submit_engine_jobs(
                    engine="stockfish",
                    endpoint=stockfish_endpoint,
                    stockfish_threads=stockfish_threads,
                    stockfish_hash_mb=stockfish_hash_mb,
                    lc0_nodes=lc0_nodes,
                    lc0_network=lc0_network,
                )
                duration = time.time() - sf_start_time
                _log_system_event(
                    "stockfish_dispatch",
                    "completed",
                    details={"submitted": n},
                    duration_seconds=duration,
                )
                log.info("Stockfish sweep complete: submitted=%d", n)
            except Exception as e:
                duration = time.time() - sf_start_time
                _log_system_event(
                    "stockfish_dispatch",
                    "failed",
                    error_message=str(e),
                    duration_seconds=duration,
                )
                log.exception("Stockfish submission sweep failed")
            last_sf = now

        if now - last_lc0 >= lc0_poll_interval:
            lc0_start_time = time.time()
            _log_system_event("lc0_dispatch", "started")
            try:
                n = _submit_engine_jobs(
                    engine="lc0",
                    endpoint=lc0_endpoint,
                    stockfish_threads=stockfish_threads,
                    stockfish_hash_mb=stockfish_hash_mb,
                    lc0_nodes=lc0_nodes,
                    lc0_network=lc0_network,
                )
                duration = time.time() - lc0_start_time
                _log_system_event(
                    "lc0_dispatch",
                    "completed",
                    details={"submitted": n},
                    duration_seconds=duration,
                )
                log.info("Lc0 sweep complete: submitted=%d", n)
            except Exception as e:
                duration = time.time() - lc0_start_time
                _log_system_event(
                    "lc0_dispatch",
                    "failed",
                    error_message=str(e),
                    duration_seconds=duration,
                )
                log.exception("Lc0 submission sweep failed")
            last_lc0 = now

        time.sleep(1)
