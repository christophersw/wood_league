# Engine Dispatch & Worker API Client Design

**Date:** 2026-05-08
**Issue:** [#1 — engine-type filtering](https://github.com/christophersw/wood_league/issues/1)
**Branch:** `issue/1-engine-type-filtering`

---

## Problem

Analysis workers currently claim jobs by connecting directly to the database via SQLAlchemy. This bypasses the Django app entirely, meaning:

- No engine-type filtering — a Stockfish worker can claim an lc0 job and vice versa
- No central orchestration — duplicate work is possible
- RunPod workers and local workers share an unguarded queue

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Django App (API)                   │
│  /api/jobs/checkout  /api/jobs/<id>/complete  etc.  │
│  claim_jobs() filters: engine + dispatch_mode=pull  │
└────────────┬──────────────────────────┬─────────────┘
             │ HTTP                     │ HTTP
    ┌────────▼────────┐       ┌────────▼────────────┐
    │  Local Stockfish │       │     Local lc0        │
    │     worker       │       │      worker          │
    │ (worker_client)  │       │  (worker_client)     │
    └──────────────────┘       └─────────────────────┘

┌─────────────────────────────────────────────────────┐
│            RunPod Dispatcher (middleware)            │
│  Polls for dispatch_mode=runpod + status=pending    │
│  Submits to RunPod → RunPod pod calls complete API  │
└─────────────────────────────────────────────────────┘
```

**Key principles:**
- Workers have no direct database access — all interaction goes through the Django API
- The Django API owns all queue logic: claiming, retries, stale recovery, deduplication
- `dispatch_mode` controls routing at enqueue time
- The RunPod dispatcher is the only process that submits jobs to RunPod

---

## Section 1: `dispatch_mode` Field

### Model change

Add to `AnalysisJob` in `services/app/analysis/models.py`:

```python
dispatch_mode = models.CharField(
    max_length=16,
    default="pull",
    db_index=True,
    choices=[("pull", "Pull"), ("runpod", "RunPod")],
)
```

### Migration

Django migration adds the column with default `"pull"`. All existing jobs become pull jobs automatically — no backfill needed.

### Index

Add compound index `(status, engine, dispatch_mode)` to replace the existing `(status, engine)` index, keeping the checkout query fast with the new filter.

### `claim_jobs()` update

`analysis/services/jobs.py` — add `dispatch_mode="pull"` to all `AnalysisJob.objects.filter(...)` calls inside `claim_jobs()` and `recover_stale_jobs()`. RunPod jobs are invisible to pull workers.

---

## Section 2: `wood_league_shared.worker_client`

### Location

```
packages/shared/wood_league_shared/worker_client/
├── __init__.py       # exports WorkerClient, WorkerClientError
├── client.py         # WorkerClient class
└── models.py         # dataclasses: Job, CheckoutResponse
```

### `Job` dataclass

```python
@dataclass
class Job:
    id: int
    game_id: str
    pgn: str
    engine: str
    depth: int
    nodes: int | None
```

### `WorkerClient`

Instantiated with `base_url` and `api_key`. Methods:

```python
client.checkout(engine, worker_id, batch_size=1) -> list[Job]
client.complete_stockfish(job_id, worker_id, payload) -> None
client.complete_lc0(job_id, worker_id, payload) -> None
client.fail(job_id, worker_id, error) -> str  # "requeued" | "failed"
client.heartbeat(worker_id, engine, status_message) -> None
```

### Error handling

- All methods raise `WorkerClientError` on non-2xx responses
- Automatic retry on 5xx: 3 attempts, exponential backoff
- No retry on 4xx — these are programming errors
- HTTP transport: `httpx`

### Config

From environment variables: `WORKER_API_URL`, `WORKER_API_KEY`

---

## Section 3: Pull Worker Rewrite

Both `services/stockfish_worker/` and `services/lc0_worker/` are rewritten to use `WorkerClient`. The engine analysis code (`analyze_pgn`, lc0 analysis) is untouched.

### New worker loop (Stockfish example)

```python
client = WorkerClient(url=WORKER_API_URL, api_key=WORKER_API_KEY)

while True:
    jobs = client.checkout(engine="stockfish", worker_id=WORKER_ID)
    if not jobs:
        client.heartbeat(WORKER_ID, engine="stockfish", status_message="idle")
        time.sleep(poll_interval)
        continue

    for job in jobs:
        try:
            result = analyze_pgn(job.pgn, depth=job.depth, ...)
            client.complete_stockfish(job.id, WORKER_ID, result)
        except Exception as exc:
            client.fail(job.id, WORKER_ID, str(exc))
```

### Deleted code

All SQLAlchemy-based infrastructure is removed from both workers:
- `_claim_job()`, `_save_analysis()`, `_mark_completed()`, `_mark_failed()`
- `_recover_stale_jobs()`, `_load_pgn()`
- All SQLAlchemy imports and `DATABASE_URL` config

### Retired entirely

- `services/app/app/ingest/analysis_worker.py`
- `services/app/app/ingest/lc0_analysis_worker.py`
- `services/app/app/ingest/run_lc0_worker.py`

---

## Section 4: RunPod Dispatcher

### Location

`services/dispatchers/` — already exists. Currently uses SQLAlchemy directly. This service also handles Chess.com ingest — that functionality is unchanged. Only the job submission path migrates to the Django API.

### What changes

The dispatcher currently queries `AnalysisJob` via SQLAlchemy and submits all pending jobs (filtered by engine) to RunPod. After this change it will:

1. Call `GET /api/queue-status` to check for pending `dispatch_mode="runpod"` jobs (or a new dedicated endpoint)
2. Call `POST /api/jobs/checkout` with `dispatch_mode="runpod"` to claim jobs before submission — preventing double-submission
3. Embed PGN in the RunPod payload (same as today — RunPod pods receive PGN directly, no pod-side fetch needed)
4. On successful RunPod submission, call a new `POST /api/jobs/<id>/submit` endpoint to record `runpod_job_id` and set status to `submitted`

### New Django API endpoint

`POST /api/jobs/<id>/submit` — authenticated, records `runpod_job_id` and transitions status from `running` → `submitted`. Called by the dispatcher after a successful RunPod submission.

### RunPod pod flow (unchanged)

1. Pod receives PGN + parameters in the RunPod job payload
2. Pod processes the game
3. Pod calls `POST /api/jobs/<id>/complete` with results

### Ingest

`_run_ingest_sweep()` and Chess.com sync remain in the dispatcher unchanged, except that newly enqueued jobs will have `dispatch_mode` set appropriately at creation time.

---

## What Is Not In Scope

- RunPod pod internals (how the pod runs the engine)
- Changes to enqueue logic beyond adding `dispatch_mode`
- Admin UI for managing `dispatch_mode`
- Chess.com ingest logic in `services/dispatchers/`

---

## Files Changed Summary

| File | Change |
|------|--------|
| `services/app/analysis/models.py` | Add `dispatch_mode` field |
| `services/app/analysis/migrations/` | New migration |
| `services/app/analysis/services/jobs.py` | Filter on `dispatch_mode="pull"` in `claim_jobs()` and `recover_stale_jobs()` |
| `services/app/api/views.py` | Add `POST /api/jobs/<id>/submit` view |
| `services/app/api/serializers.py` | Add submit request serializer |
| `services/app/api/urls.py` | Wire new view |
| `packages/shared/wood_league_shared/worker_client/` | New module (`client.py`, `models.py`, `__init__.py`) |
| `services/stockfish_worker/` | Rewrite to use `WorkerClient` — remove SQLAlchemy |
| `services/dispatchers/` | Migrate job submission to Django API — remove SQLAlchemy for job ops; keep ingest |
| `services/app/app/ingest/analysis_worker.py` | Delete |
| `services/app/app/ingest/lc0_analysis_worker.py` | Delete |
| `services/app/app/ingest/run_lc0_worker.py` | Delete |
