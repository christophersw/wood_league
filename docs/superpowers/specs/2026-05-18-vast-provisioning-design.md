# Cron-Driven vast.ai Analysis Provisioning — Design

**Status:** Draft (2026-05-18)
**Issue:** #155 (reshaped — see "Scope change vs. the issue" below)
**Components:** `services/app` (Django), a new Railway cron service
**Refs:** #150 (cold-start cache, shipped 0.9.16), #152 (headless run hardening, shipped); mirrors the legacy RunPod admin path (`analysis/views.py::runpod_start_view`, `analysis/services/runpod_dispatch.py`)

## Background

vast.ai on-demand instances **never self-stop** — they bill until something
explicitly destroys them. Today a vast analysis worker is launched only
out-of-band (the `vastai` CLI or the vast console launching a saved
template), and nothing in the app owns its lifecycle. Issue #155 originally
framed this as an admin "spin up / tear down" button mirroring the dormant
RunPod path. Brainstorming reshaped it: the real need is a recurring,
cost-safe batch — provision a worker, drain a capped number of queued
analysis jobs, and guarantee teardown — with no live UI surface.

The vast worker is a **pull** worker: given `WL_CAMPAIGN_ID` and
`WLW_MAX_JOBS`, it pulls up to that many jobs from the existing queue and
self-exits when the batch is drained (#152 hardened it so it no longer
silently aborts on missing env). The lifecycle problem is therefore not
"keep a box alive" but "launch a finite batch and reliably destroy the box
afterward, even when things crash."

## Scope change vs. the issue

Confirmed with the user during brainstorming:

- **In scope:** a single idempotent **45-minute reconcile cron** that
  launches a vast worker when analysis is scheduled and destroys it when the
  batch drains or a hard deadline passes; two small tables; vast REST client;
  settings/secrets; gating; tests.
- **Out of scope (explicitly deferred by the user):** how games get into
  the queue, "newly ingested"/recency filtering, backlog-cleared detection,
  campaign *creation*, the in-app admin button/UI, and any worker-side code
  changes. The orchestrator processes whatever is already queued, with no
  concern for how or when it got there.

## Goal

After this ships, an admin (or any app-side actor) records an intent to run
analysis; within ≤45 min a vast worker is provisioned to drain up to a
configured cap of queued jobs; and within ≤45 min of that batch finishing —
or immediately past a hard deadline — the instance is destroyed. No GPU box
can leak indefinitely regardless of crashes, redeploys, or hangs.

## Design

### Control model: one idempotent reconcile loop

A single Django management command, `reconcile_vast_analysis`, runs every
45 minutes as a Railway cron service. It holds **no long-lived process** and
keeps **no in-memory state** — every run re-derives "what should be true"
from two tables and converges. This is what makes it crash-safe: a Railway
redeploy, OOM, or crash between ticks is harmless; the next tick reconciles.

Each run, in strict order:

1. **Reap first.** For every `AnalysisInstance` not in a terminal state:
   - If past `hard_deadline` → destroy (cost backstop, unconditional).
   - Else if its batch is **drained** → destroy (happy path). Drained is
     detected via the **worker's heartbeat going stale**, not a job-count
     query (there is no campaign/run scoping on `AnalysisJob` — only global
     status counts and `WorkerHeartbeat` rows exist). See "Drained
     detection" below.
   - On a successful vast destroy, set status `destroyed` and stamp
     `destroyed_at`. Destroy is retried with backoff within the run; a
     run that fails to destroy leaves the row non-terminal so the **next**
     tick retries — destruction is never abandoned.
   - **Schedule status recovery (end of reap):** for any `AnalysisSchedule`
     in `running` whose only/last `AnalysisInstance` is terminal, settle the
     schedule (`done` if the instance was `destroyed` cleanly, else
     `failed`). This prevents a stuck `running` schedule from deadlocking
     all future launches.
2. **Launch second.** Only if **no** `AnalysisInstance` is currently live
   (statuses `launching`/`running`) — never two boxes at once — **and** the
   oldest `pending` `AnalysisSchedule` row exists (FIFO; one schedule at a
   time):
   - Search vast offers first. On no qualifying offer, record **nothing**
     and leave the schedule `pending` (a search creates no box, so there
     is nothing to recover; retried next tick). This avoids accumulating
     dead rows on repeated no-offer ticks.
   - Once an offer is in hand, write an `AnalysisInstance` row with status
     `launching` *before* the create call (the create is the billable,
     crash-sensitive step the reaper must be able to recover).
   - Create the instance from the configured template hash with per-run
     env, label it with the schedule id.
   - On success: store the vast instance id, set status `running`, set
     `hard_deadline = now + VAST_HARD_DEADLINE_HOURS`, mark the schedule
     `running`. On failure: set the row `failed`, mark the schedule
     `failed`, log; do not retry within the same run.

Reap-before-launch guarantees a finished/overdue box is always torn down
before a new one is considered, so the "max one instance" invariant also
caps spend.

### Crash-gap robustness (launch path)

The dangerous gap is "vast instance created but the DB write of its id was
lost." Mitigations, layered:

- The `launching` row is written after a successful offer search but
  before the (billable) create call, so the reaper sees *something* is in
  flight for any box that could exist. A no-offer tick writes no row
  because no box was created.
- The vast instance is created with a label/env `WL_SCHEDULE_ID=<id>`. The
  reap pass also lists live vast instances via the API and destroys any
  carrying a `WL_SCHEDULE_ID` whose `AnalysisInstance` is terminal/absent —
  this catches an orphan even if its DB id was never persisted.
- A `launching` row older than `VAST_LAUNCH_GRACE_MINUTES` with no vast id
  is reconciled: attempt orphan discovery by label, then mark `failed`.

### Drained detection (happy-path teardown trigger)

There is **no `campaign` field on `AnalysisJob`** — `WL_CAMPAIGN_ID` is a
worker-side env only. The data model exposes only global job-status counts
(`analysis.services_queries.queue_totals()`) and `WorkerHeartbeat` rows
(`worker_id` PK, `last_seen` auto-updated, `status`, `batch_total`,
`batch_processed`). Global "queue empty" is the **wrong** signal: the
worker is capped at `WLW_MAX_JOBS` and self-exits after its slice while a
backlog-fed queue may still have thousands pending — that would never
trip a drained signal and would waste GPU until `hard_deadline`.

Correct signal — **worker gone via stale heartbeat** (chosen by user):

- The vast worker self-exits when its `WLW_MAX_JOBS` batch is drained;
  once the process is gone it stops updating its `WorkerHeartbeat`, so
  `last_seen` ages.
- **Correlation** (unambiguous because of the ≤1-live-instance invariant):
  at launch the command snapshots the set of existing
  `WorkerHeartbeat.worker_id`s into the new `AnalysisInstance.worker_id`
  as *unset*; on a later tick, the first `WorkerHeartbeat` whose
  `last_seen >= AnalysisInstance.launched_at` and whose `worker_id` was
  **not** in the launch snapshot is bound to this instance
  (`AnalysisInstance.worker_id` is set). Only one instance is ever live,
  so "a worker that appeared after this launch" is unambiguous.
- **Drained** = the bound worker's `WorkerHeartbeat.last_seen` is older
  than `VAST_WORKER_STALE_MINUTES` (worker exited), **or** the bound
  heartbeat reports `batch_total` is not null and
  `batch_processed >= batch_total` (worker reported its cap done).
- If no worker has bound yet and the instance is older than
  `VAST_WORKER_STALE_MINUTES` past `launched_at` (worker never started /
  failed to register), the instance is treated as drained-failed and
  destroyed — no separate hang case needed before `hard_deadline`.
- `hard_deadline` remains the unconditional absolute backstop above all
  of this.

The launch snapshot is stored on the `AnalysisInstance` so detection is
still stateless-per-run (re-derivable every tick from the tables).

### Data model (two tables, `analysis` app)

`AnalysisSchedule` — app-written intent (this *is* the "manual trigger";
no UI button):
- `id`, `created_at`
- `status`: `pending` → `running` → `done` | `failed`
- `max_jobs` (int, nullable; defaults to `VAST_MAX_JOBS` when null)
- `note` (optional free text, e.g. who/why)

`AnalysisInstance` — live truth + teardown backstop:
- `id`, `schedule` (FK → `AnalysisSchedule`), `created_at`
- `status`: `launching` → `running` → `destroyed` | `failed`
- `vast_instance_id` (nullable until create succeeds)
- `launched_at`, `hard_deadline`, `destroyed_at` (nullable)
- `offer_dph` (the $/hr actually accepted, for cost visibility)
- `launch_worker_ids` (JSON list — snapshot of existing
  `WorkerHeartbeat.worker_id`s at launch, for drained correlation)
- `worker_id` (nullable str — the `WorkerHeartbeat` bound to this
  instance once a post-launch worker appears; null until correlated)

Both registered in Django admin (read-mostly; `AnalysisSchedule` insertable)
— Django admin is the lightweight "app provides input" surface and the
operator's window into live/teardown state. No new views/templates.

### Input ("manual trigger")

Insert a `pending` `AnalysisSchedule` row via Django admin, or directly via
DB / Railway. The cron picks it up on its next tick. There is deliberately
no synchronous launch path.

### vast.ai client — `analysis/services/vast_dispatch.py`

Mirrors `runpod_dispatch.py`'s shape. Thin wrapper over the vast REST API
(the same API the `vastai` CLI wraps):

- `search_offers()` → offers filtered by `VAST_OFFER_GPU_NAME` and
  `dph_total <= VAST_OFFER_MAX_DPH`, sorted cheapest-first; returns the
  chosen offer or raises if none qualify.
- `create_instance(offer_id, *, template_hash, env)` → creates from
  `VAST_TEMPLATE_HASH`; per-run env merges with the template env (vast
  merges, not replaces): `WL_CAMPAIGN_ID`, `WLW_MAX_JOBS`,
  `WL_SCHEDULE_ID`. Returns the new vast instance id.
- `destroy_instance(vast_instance_id)` → idempotent; treats
  already-gone/404 as success.
- `list_instances()` → for orphan discovery by `WL_SCHEDULE_ID` label.

All calls structured-logged (never log `VAST_API_KEY`), return
`{"ok", "status_code", "message", ...}`-style results consistent with the
RunPod helper.

### Settings / secrets

New Django settings (env-backed), mirroring the `RUNPOD_*` gating idiom:

- `VAST_ENABLED` (bool, default False) — when False the management command
  no-ops and logs a single line; nothing else in the design activates.
  Same "invisible when off" posture as `RUNPOD_ENABLED`.
- `VAST_API_KEY` (secret; never on the rented box — the key stays in-app,
  used only by the cron)
- `VAST_TEMPLATE_HASH` (per-release, version-pinned; config, not hardcoded)
- `VAST_CAMPAIGN_ID` (passthrough config; orchestrator does not compute it)
- `VAST_OFFER_GPU_NAME` (e.g. `L40S`), `VAST_OFFER_MAX_DPH` ($/hr ceiling)
- `VAST_MAX_JOBS` (default **100**)
- `VAST_HARD_DEADLINE_HOURS` (absolute kill regardless of job state)
- `VAST_LAUNCH_GRACE_MINUTES` (stale-`launching` reconcile threshold)
- `VAST_WORKER_STALE_MINUTES` (heartbeat-staleness window that means the
  worker exited → batch drained; also the "worker never registered"
  failure window measured from `launched_at`)

### Railway cron

One Railway cron service running `python manage.py
reconcile_vast_analysis` every 45 minutes. The command must be safe to run
when `VAST_ENABLED` is False (no-op) and safe to overlap-skip — runs are
short and idempotent, but a slow run must not double-launch (the
"no live instance" precondition already prevents this).

## Cost-safety properties (the point of the whole design)

- **Bounded idle:** a drained box lives at most one tick (~45 min,
  ~22 min average) before reap destroys it.
- **Hard ceiling:** `hard_deadline` destroys a hung/stuck box
  unconditionally — the catastrophic case is capped, not open-ended.
- **Crash-safe:** state lives in tables, not a process; any crash/redeploy
  is reconciled on the next tick. Orphans are recoverable by vast-side
  label even if a DB write was lost.
- **At most one instance** ever live → spend is capped at one box's $/hr.
- **No key on untrusted infra:** `VAST_API_KEY` only ever lives in the
  app/cron, never on the rented instance.

## Error handling

- vast API/network failure on **create** → row `failed`, schedule
  `failed`, logged; next pending schedule (if any) tried next tick.
- vast failure on **destroy** → row stays non-terminal; retried with
  backoff this run and again every tick until it succeeds (destruction is
  never given up on).
- No qualifying offer under `VAST_OFFER_MAX_DPH` → no launch, logged;
  reconsidered next tick (price/availability moves).
- `VAST_ENABLED` False or required setting missing → no-op + single log
  line; validate required env before any launch (#152 lesson).
- Stale `launching` row → orphan-discover by label, else `failed`.

## Testing

- `reconcile_vast_analysis` unit tests with the vast client mocked:
  pending→launch, no-pending→no-op, live-instance→no second launch,
  drained→destroy, past-deadline→destroy, destroy-fails→retry next tick,
  `VAST_ENABLED` False→no-op, stale-`launching`→orphan path.
- `vast_dispatch` tests with mocked HTTP: offer filtering/sort, price
  ceiling rejection, create env-merge payload, destroy idempotency on 404,
  no-API-key guard, key never logged.
- Model tests: status transitions, default `max_jobs`, admin insertability.
- Mirror `analysis/tests/test_runpod_admin.py` structure where it maps.

## Out of scope / non-goals

Game selection & enqueueing, recency/"newly ingested" filtering,
backlog-cleared gating, campaign creation, in-app admin button or any
web view/template, worker-side code changes, multi-instance/parallel
fan-out, stop/start (only create/destroy), auto-scaling by queue depth.
