"""
Title: main.py — Unified Wood League dispatcher
Description:
    Periodically ingests Chess.com games (via ChessComSyncService + SQLAlchemy),
    enqueues new jobs, and submits pending RunPod jobs to RunPod by claiming them
    through the Django API (WorkerClient).

    The ingest path (Chess.com sync, job creation) retains its SQLAlchemy
    connection because the Django app cannot expose an ingest-write API today.
    The dispatch path (claiming, submitting, recording) uses WorkerClient only.

Changelog:
    2026-05-08 (#1): Migrate job dispatch from SQLAlchemy to WorkerClient HTTP API
    2026-05-10: Removed dispatch_mode references from checkout() call and AnalysisJob creation
"""
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
from wood_league_shared.storage.models import AnalysisJob, SystemEvent
from wood_league_shared.worker_client import WorkerClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dispatchers")

_DISPATCHER_WORKER_ID = "runpod-dispatcher"


def _log_system_event(
    event_type: str,
    status: str,
    details: dict | None = None,
    error_message: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """Log a system event to the database.

    Args:
        event_type: Type of event (e.g., "ingest", "stockfish_dispatch")
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
    except Exception as exc:
        log.error("Failed to log system event: %s", exc)


def _required_env(name: str) -> str:
    """Return the named environment variable, raising RuntimeError if unset.

    Args:
        name: Environment variable name.

    Returns:
        Non-empty string value of the variable.

    Raises:
        RuntimeError: If the variable is missing or empty.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _endpoint_ids() -> tuple[str, str]:
    """Resolve the Stockfish and Lc0 RunPod endpoint IDs from environment.

    Returns:
        Tuple of (stockfish_endpoint_id, lc0_endpoint_id).

    Raises:
        RuntimeError: If either endpoint ID is not configured.
    """
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
    """Parse a boolean from a string environment variable.

    Args:
        value: Raw string value (or None).
        default: Return value when the input is None or unrecognized.

    Returns:
        Parsed boolean.
    """
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_usernames(raw: str) -> list[str]:
    """Parse a comma-separated list of Chess.com usernames.

    Args:
        raw: Comma-separated string of usernames.

    Returns:
        List of lowercase username strings.
    """
    if not raw.strip():
        return []
    return [u.strip().lower() for u in raw.split(",") if u.strip()]


def _build_runpod_payload(
    job,
    engine: str,
    stockfish_threads: int,
    stockfish_hash_mb: int,
    lc0_nodes: int,
    lc0_network: str,
) -> dict:
    """Build the RunPod job payload for a claimed analysis job.

    Args:
        job: Job dataclass from WorkerClient.checkout().
        engine: 'stockfish' or 'lc0'
        stockfish_threads: Thread count for Stockfish jobs.
        stockfish_hash_mb: Hash table size for Stockfish jobs.
        lc0_nodes: Default node budget for lc0 jobs.
        lc0_network: Optional weights path for lc0 jobs.

    Returns:
        Dict to pass to endpoint.run().
    """
    if engine == "stockfish":
        return {
            "job_id": job.id,
            "pgn": job.pgn,
            "depth": job.depth,
            "threads": stockfish_threads,
            "hash_mb": stockfish_hash_mb,
        }
    payload: dict = {
        "job_id": job.id,
        "pgn": job.pgn,
        "nodes": job.nodes if job.nodes else lc0_nodes,
    }
    if lc0_network:
        payload["weights_path"] = lc0_network
    return payload


def _submit_one_job(*, client: WorkerClient, job, engine: str, endpoint, **kwargs) -> bool:
    """Attempt to submit a single claimed job to RunPod and record the result.

    Args:
        client: Authenticated WorkerClient instance.
        job: Job dataclass from checkout().
        engine: 'stockfish' or 'lc0'
        endpoint: RunPod Endpoint for the engine.
        **kwargs: Forwarded to _build_runpod_payload.

    Returns:
        True if submitted successfully, False on error.
    """
    if not job.pgn:
        log.warning("%s job_id=%d game_id=%s has no PGN — skipping", engine, job.id, job.game_id)
        client.fail(job_id=job.id, worker_id=_DISPATCHER_WORKER_ID, error="No PGN")
        return False
    try:
        payload = _build_runpod_payload(job, engine, **kwargs)
        run_request = endpoint.run(payload)
        client.submit_runpod(job_id=job.id, runpod_job_id=run_request.job_id)
        log.info(
            "Submitted %s job_id=%d game_id=%s -> runpod_job_id=%s",
            engine, job.id, job.game_id, run_request.job_id,
        )
        return True
    except Exception:
        log.exception("Failed submitting %s job_id=%d game_id=%s", engine, job.id, job.game_id)
        return False


def _submit_engine_jobs(
    *,
    client: WorkerClient,
    engine: str,
    endpoint,
    limit: int | None = None,
    stockfish_threads: int = 8,
    stockfish_hash_mb: int = 2048,
    lc0_nodes: int = 25000,
    lc0_network: str = "",
) -> int:
    """Claim pending runpod jobs from the API and submit them to RunPod.

    Claims batches of jobs from the Django API, submits each to RunPod, then
    records the RunPod job ID via the submit endpoint.

    Args:
        client: Authenticated WorkerClient instance.
        engine: 'stockfish' or 'lc0'
        endpoint: RunPod Endpoint object for the given engine.
        limit: Maximum jobs to submit this sweep (None = all pending).
        stockfish_threads: Threads for Stockfish RunPod payload.
        stockfish_hash_mb: Hash MB for Stockfish RunPod payload.
        lc0_nodes: Default node budget for lc0 jobs.
        lc0_network: Optional weights path for lc0 jobs.

    Returns:
        Number of jobs successfully submitted to RunPod this sweep.
    """
    submitted = 0
    payload_kwargs = dict(
        stockfish_threads=stockfish_threads,
        stockfish_hash_mb=stockfish_hash_mb,
        lc0_nodes=lc0_nodes,
        lc0_network=lc0_network,
    )

    while True:
        jobs = client.checkout(
            engine=engine,
            worker_id=_DISPATCHER_WORKER_ID,
            batch_size=10,
        )
        if not jobs:
            break

        for job in jobs:
            if _submit_one_job(client=client, job=job, engine=engine, endpoint=endpoint, **payload_kwargs):
                submitted += 1

        if limit is not None and submitted >= limit:
            break

    return submitted


def _enqueue_job_if_needed(*, session, game_id: str, engine: str, depth: int) -> bool:
    """Create a runpod-mode AnalysisJob for a game if one does not already exist.

    Args:
        session: Active SQLAlchemy session.
        game_id: Game to enqueue.
        engine: 'stockfish' or 'lc0'
        depth: Analysis depth (Stockfish) or node count (lc0).

    Returns:
        True if a new job was added to the session, False if skipped.
    """
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


def _enqueue_new_game_jobs(
    *,
    game_ids: list[str],
    queue_stockfish: bool,
    queue_lc0: bool,
    stockfish_depth: int,
    lc0_nodes: int,
) -> tuple[int, int]:
    """Enqueue analysis jobs for a list of newly-ingested game IDs.

    Args:
        game_ids: Game IDs that were inserted by the ingest sweep.
        queue_stockfish: Whether to create Stockfish jobs.
        queue_lc0: Whether to create lc0 jobs.
        stockfish_depth: Depth to use for Stockfish jobs.
        lc0_nodes: Node budget for lc0 jobs.

    Returns:
        Tuple of (stockfish_enqueued, lc0_enqueued) counts.
    """
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
    """Sync Chess.com archives and enqueue jobs for newly ingested games.

    Args:
        usernames: List of Chess.com usernames to sync.
        ingest_month_limit: Number of months of history to fetch.
        chess_com_user_agent: User-Agent header for Chess.com requests.
        queue_stockfish_after_ingest: Create Stockfish jobs for new games.
        queue_lc0_after_ingest: Create lc0 jobs for new games.
        stockfish_depth: Depth for Stockfish jobs.
        lc0_nodes: Node budget for lc0 jobs.

    Returns:
        Tuple of (inserted, updated, archives_scanned, sf_enqueued, lc0_enqueued).
    """
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
    inserted_game_ids: list[str] = [
        gid for r in results for gid in r.inserted_game_ids
    ]

    enqueued_sf, enqueued_lc0 = _enqueue_new_game_jobs(
        game_ids=inserted_game_ids,
        queue_stockfish=queue_stockfish_after_ingest,
        queue_lc0=queue_lc0_after_ingest,
        stockfish_depth=stockfish_depth,
        lc0_nodes=lc0_nodes,
    )

    return inserted, updated, archives, enqueued_sf, enqueued_lc0


def main() -> None:
    """Start the dispatcher loop: periodically ingest and submit jobs to RunPod."""
    runpod.api_key = _required_env("RUNPOD_API_KEY")
    worker_api_url = _required_env("WORKER_API_URL")
    worker_api_key = _required_env("WORKER_API_KEY")
    stockfish_endpoint_id, lc0_endpoint_id = _endpoint_ids()

    stockfish_endpoint = runpod.Endpoint(stockfish_endpoint_id)
    lc0_endpoint = runpod.Endpoint(lc0_endpoint_id)
    client = WorkerClient(base_url=worker_api_url, api_key=worker_api_key)

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
        "Dispatchers started: stockfish_endpoint=%s lc0_endpoint=%s api=%s",
        stockfish_endpoint_id, lc0_endpoint_id, worker_api_url,
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
                    "Ingest sweep: archives=%d inserted=%d updated=%d sf=%d lc0=%d",
                    archives, inserted, updated, enqueued_sf, enqueued_lc0,
                )
            except Exception as exc:
                duration = time.time() - ingest_start_time
                _log_system_event("ingest", "failed", error_message=str(exc), duration_seconds=duration)
                log.exception("Chess.com ingest sweep failed")
            last_ingest = now

        if now - last_sf >= sf_poll_interval:
            sf_start_time = time.time()
            _log_system_event("stockfish_dispatch", "started")
            try:
                n = _submit_engine_jobs(
                    client=client,
                    engine="stockfish",
                    endpoint=stockfish_endpoint,
                    stockfish_threads=stockfish_threads,
                    stockfish_hash_mb=stockfish_hash_mb,
                    lc0_nodes=lc0_nodes,
                    lc0_network=lc0_network,
                )
                duration = time.time() - sf_start_time
                _log_system_event("stockfish_dispatch", "completed", details={"submitted": n}, duration_seconds=duration)
                log.info("Stockfish sweep: submitted=%d", n)
            except Exception as exc:
                duration = time.time() - sf_start_time
                _log_system_event("stockfish_dispatch", "failed", error_message=str(exc), duration_seconds=duration)
                log.exception("Stockfish submission sweep failed")
            last_sf = now

        if now - last_lc0 >= lc0_poll_interval:
            lc0_start_time = time.time()
            _log_system_event("lc0_dispatch", "started")
            try:
                n = _submit_engine_jobs(
                    client=client,
                    engine="lc0",
                    endpoint=lc0_endpoint,
                    stockfish_threads=stockfish_threads,
                    stockfish_hash_mb=stockfish_hash_mb,
                    lc0_nodes=lc0_nodes,
                    lc0_network=lc0_network,
                )
                duration = time.time() - lc0_start_time
                _log_system_event("lc0_dispatch", "completed", details={"submitted": n}, duration_seconds=duration)
                log.info("Lc0 sweep: submitted=%d", n)
            except Exception as exc:
                duration = time.time() - lc0_start_time
                _log_system_event("lc0_dispatch", "failed", error_message=str(exc), duration_seconds=duration)
                log.exception("Lc0 submission sweep failed")
            last_lc0 = now

        time.sleep(1)
