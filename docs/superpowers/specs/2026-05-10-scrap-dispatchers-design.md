---
title: Scrap dispatchers service; admin-gated RunPod queue
date: 2026-05-10
status: approved-for-planning
supersedes: docs/superpowers/specs/2026-05-08-engine-dispatch-design.md (partial)
related-issue: GitHub #12 (root cause structurally eliminated)
---

# Scrap Dispatchers; Admin-Gated RunPod Queue

## Summary

Delete the `services/dispatchers` Railway service entirely. Move Chess.com ingest
into the Django app as a management command run by Railway cron. Replace
auto-dispatch to RunPod with two admin-facing queue pages (one per engine) where
an admin selects pending jobs and explicitly submits them to RunPod. Local
workers continue to claim jobs over the existing HTTP `WorkerClient` API,
unchanged.

The `AnalysisJob.dispatch_mode` column is removed: a pending job is simply
pending, and either a local worker claims it or an admin promotes it to RunPod.
First mover wins. This structurally eliminates the bug class behind issue #12
(dedup logic that ignored `dispatch_mode`).

## Motivation

The dispatcher service has accumulated three responsibilities (Chess.com ingest,
Stockfish auto-dispatch, Lc0 auto-dispatch) and one architectural smell
(SQLAlchemy direct-DB ingest path running alongside the HTTP `WorkerClient`
dispatch path in the same process). Symptoms:

- Issue #12: dedup logic in the dispatcher doesn't filter by `dispatch_mode`,
  so a stale `pull` job blocks a `runpod` job for the same game. The bug
  exists because dedup is duplicated outside the Django ORM and drifts.
- `wood_league_shared` must keep SQLAlchemy models in sync with Django ORM
  models indefinitely — this is what keeps three `User` classes alive in the
  repo.
- A roll-your-own `time.sleep(1)` polling scheduler with no backoff or retry.
- RunPod serverless costs spin-up money. Auto-dispatching every pending job is
  the wrong default; the right default is human-gated submission.

## Non-goals

- No changes to `services/local_worker` behavior or its public PyPI surface.
- No replacement of RunPod with a different provider.
- No new task queue (Celery/Django-Q). Railway cron is sufficient.
- No "unstick stale `submitted` jobs" admin action — tracked as a follow-up.
- No deletion of `wood_league_shared`. It will shrink to whatever
  `local_worker` actually imports; full removal is a separate effort.

## Architecture

Two Railway services after this change:

| Service | Responsibility |
|---|---|
| `services/app` (Django) | Web UI, REST API for workers, ingest management command, RunPod admin dispatch action |
| `services/local_worker` (PyPI) | Claims pending jobs via `WorkerClient` HTTP API. Unchanged. |

Plus one Railway cron schedule on the `app` service:

```
*/15 * * * *   python manage.py sync_games
```

Deleted: `services/dispatchers/` (entire directory).

## Data model changes

### `AnalysisJob`

| Change | Detail |
|---|---|
| **Drop** `dispatch_mode` | Column removed. Migration drops the column without backfill — existing pending jobs simply become claimable by either path. |
| **Add** `last_error: TextField(null=True)` | Set when admin RunPod submission throws. Job stays `pending` for retry. |
| **Add** `last_error_at: DateTimeField(null=True)` | Timestamp paired with `last_error`. |

`status` lifecycle (no `dispatch_mode` involved):

```
pending ──[local worker checkout]──> running ──[complete]──> completed
   │                                                    │
   └──[admin "Submit to RunPod"]─> submitted ───────────┘
                                       │
                                       └──[failed by RunPod]─> failed
```

### `SiteSettings` (new singleton model)

Single-row settings table accessible via Django admin:

| Field | Type | Default |
|---|---|---|
| `auto_enqueue_stockfish` | BooleanField | True |
| `auto_enqueue_lc0` | BooleanField | False |

Implementation: a small `SiteSettings` model with `get_solo()`-style accessor.
No `django-constance` dependency.

## Components

### `services/app/ingest/management/commands/sync_games.py` (existing, expanded)

Already exists. Audit and update so that one invocation:

1. Loads `CHESS_COM_USERNAMES` (env, comma-separated) — same source as today.
2. Acquires a Postgres advisory lock via `pg_try_advisory_lock(LOCK_ID)`,
   where `LOCK_ID` is a hardcoded module-level constant (a 32-bit int chosen
   once for this command, e.g. `0x7E57_1465`). If the lock is held, log and
   exit zero (cron-overlap protection).
3. For each username, runs the existing `ChessComSyncService` logic against
   the Django ORM (replacing any remaining SQLAlchemy code paths).
4. For each newly-inserted `Game`, calls `enqueue_analysis_job(game, engine)`
   for each engine whose `SiteSettings.auto_enqueue_*` flag is `True`.
5. Writes a `SystemEvent` row (`event_type='ingest'`, status, duration,
   counts) for observability.
6. Releases the advisory lock on exit.

### `services/app/analysis/services/runpod_dispatch.py` (new)

```python
def submit_job_to_runpod(job: AnalysisJob) -> str:
    """Submit a single pending job to RunPod, return runpod_job_id.

    Caller is responsible for the row lock and status transition.
    """
```

Pure function. Builds the engine-specific payload (the 30 lines of real logic
extracted from today's dispatcher), reads the engine's RunPod endpoint id from
Django settings (`RUNPOD_STOCKFISH_ENDPOINT_ID` / `RUNPOD_LC0_ENDPOINT_ID`),
calls `runpod.Endpoint(endpoint_id).run()`, returns the runpod job id. Raises
on RunPod error; caller handles.

### `services/app/analysis/services/enqueue.py` (new)

```python
def enqueue_analysis_job(game: Game, engine: str) -> AnalysisJob | None:
    """Create a pending AnalysisJob for game+engine if none active or
    already-completed-at-sufficient-depth exists. Returns the new job
    or None if skipped.
    """
```

Dedup filter: `engine + game_id + status in (pending, running, submitted)`,
or `status='completed' AND depth >= requested_depth`. No `dispatch_mode`
clause — that's the structural fix for #12.

### `services/app/analysis/views/queue.py` (new)

Two list views:

- `GET /admin/queue/stockfish/` → `StockfishQueueView`
- `GET /admin/queue/lc0/` → `Lc0QueueView`

Each:
- Lists `AnalysisJob.objects.filter(engine=…, status='pending')`.
- Shows columns: checkbox, game (player names + date + result), depth/nodes,
  created_at, last_error (red badge if present).
- Filter form (HTMX-driven): player, date range, opening ECO.
- Bulk action: `POST /admin/queue/<engine>/submit/` with `job_ids=[…]`.

### `POST /admin/queue/<engine>/submit/` (new)

Per submitted id, in its own transaction:

```python
with transaction.atomic():
    job = AnalysisJob.objects.select_for_update(skip_locked=True).filter(
        id=job_id, engine=engine, status='pending'
    ).first()
    if job is None:
        skipped += 1
        continue
    try:
        runpod_id = submit_job_to_runpod(job)
        job.status = 'submitted'
        job.runpod_job_id = runpod_id
        job.last_error = None
        job.last_error_at = None
        job.save()
        submitted += 1
    except Exception as exc:
        job.last_error = str(exc)[:1000]
        job.last_error_at = timezone.now()
        job.save()
        failed += 1
```

Returns `{submitted, skipped, failed, errors}` for HTMX swap. The queue page
renders updated rows inline (failed jobs show a red badge with the error).

### Removed

- Whole `services/dispatchers/` directory.
- Any `WorkerClient.checkout(..., dispatch_mode=...)` filter argument.
- `dispatch_mode` column and any code referencing it across the repo.

## Concurrency & races

| Race | Resolution |
|---|---|
| Local worker + admin click same job | `select_for_update(skip_locked=True)` in checkout and admin submit. First tx wins; second sees `status != 'pending'` and skips. |
| Two admins click same job | Same mechanism. Second admin's row falls out of the locked set. |
| Bulk submit, RunPod fails on one job | Per-job transaction. Successes commit; failed job stays `pending` with `last_error`. |
| Cron overlap (sweep > interval) | `pg_try_advisory_lock` at start of `sync_games`; second invocation exits zero. |
| RunPod completion webhook retried | Existing `complete_job` view must be idempotent — confirm during implementation. |

## Configuration

### Environment (Django app)

Already-set vars stay as-is. Add nothing new. Drop from dispatcher's old set:

| Drop | Why |
|---|---|
| `SF_POLL_INTERVAL`, `LC0_POLL_INTERVAL` | No more polling. |
| `QUEUE_STOCKFISH_AFTER_INGEST`, `QUEUE_LC0_AFTER_INGEST` | Replaced by `SiteSettings` toggles in admin. |
| `INGEST_POLL_INTERVAL` | Replaced by Railway cron schedule. |

Keep:

| Var | Used by |
|---|---|
| `RUNPOD_API_KEY`, `RUNPOD_STOCKFISH_ENDPOINT_ID`, `RUNPOD_LC0_ENDPOINT_ID` | Django app's `submit_job_to_runpod`. |
| `CHESS_COM_USERNAMES`, `CHESS_COM_USER_AGENT`, `INGEST_MONTH_LIMIT` | `sync_games` command. |
| `ANALYSIS_DEPTH`, `ANALYSIS_THREADS`, `ANALYSIS_HASH_MB`, `LC0_NODES`, `LC0_NETWORK` | Job creation defaults; same as today. |

### Railway

- `services/app/railway.toml`: declare cron schedule (every 15 min) running
  `python manage.py sync_games`.
- Delete the dispatchers Railway service.

## Testing

### Unit

- `submit_job_to_runpod(job)`: mock `runpod.Endpoint.run`; assert payload
  shape for stockfish vs lc0; assert `runpod_job_id` is returned.
- `enqueue_analysis_job(game, engine)` dedup matrix:
  - no existing job → creates
  - pending exists → skips
  - running exists → skips
  - submitted exists → skips
  - completed at `depth >= requested` → skips
  - completed at lower depth → creates new job

### Integration (Django test DB)

- `sync_games` end-to-end with mocked Chess.com archive: inserts games,
  respects `SiteSettings` toggles, emits `SystemEvent`.
- Bulk submit view: select 3 jobs, mock `endpoint.run`, assert all 3
  transition to `submitted` and HTMX response is correct.
- Race: two simultaneous bulk submits on the same job — one succeeds, one
  is counted as skipped, RunPod called exactly once.
- Cron overlap: two simultaneous `sync_games` calls — second exits via
  advisory lock.
- Migration: data preservation — pre/post `AnalysisJob` row count identical;
  no status changes on existing `running`/`submitted` jobs.

### Manual smoke test (pre-deploy)

1. Run `sync_games` locally against a real Chess.com username. Confirm new
   games appear and jobs are auto-enqueued per `SiteSettings` toggles.
2. Open `/admin/queue/stockfish/`, check two jobs, click Submit to RunPod.
   Confirm rows go `submitted` and the RunPod console shows the run.
3. Wait for completion webhook; confirm rows go `completed`.
4. Start `local_worker` against the same DB; confirm it claims a different
   pending job and processes it normally.

## Migration plan (deploy ordering)

1. Ship Django changes (new models, services, views, sync_games update).
   `dispatch_mode` column still present; no behavior change yet.
2. Configure Railway cron on `app` service. Verify `sync_games` runs
   cleanly.
3. Stop the dispatchers Railway service. Verify no jobs are being
   auto-submitted to RunPod and the queue UI works.
4. Ship migration that drops `dispatch_mode`. (Two-phase deploy avoids a
   moment where old dispatcher code is running against new schema.)
5. Delete `services/dispatchers/` directory in a follow-up commit.

## Out of scope / follow-ups

- Audit `wood_league_shared` and remove SQLAlchemy models that no consumer
  imports.
- "Unstick stale submitted jobs" admin action (timeout-based recovery).
- Per-user / per-club auto-enqueue settings (only relevant once there are
  multiple clubs).
- Cost guardrails ("warn if submitting >N jobs at once").
