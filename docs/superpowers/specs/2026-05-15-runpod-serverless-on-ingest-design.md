# RunPod serverless on-ingest analysis (coexisting with pod model)

- **Date:** 2026-05-15
- **Components:** `services/app` (ingest + dispatch), `services/lc0_worker`,
  `services/stockfish_worker`, RunPod serverless endpoints
- **Status:** Approved (brainstorming) — pending spec review
- **Related:** Issue #101 (pull model), #106 (removed serverless health probe),
  #119 (TRT backend), `services/app/runpod plan.md` (2026-04-19 original
  serverless migration plan — superseded by this scoped, coexisting design)

## Problem

Bulk analysis runs on RunPod **pods** that poll `/api/v1/jobs/checkout/`
(pull model, established by #101). Small, on-demand analysis (a handful of
freshly ingested games) currently requires manually spinning up a pod and
pays for idle pod time. We want freshly ingested games analysed
automatically with **$0 idle cost**, **without** manually starting a pod,
and **without** abandoning the pod model for bulk backlog.

## Goals

1. No manual pod spin-up for small/on-demand analysis.
2. Analysis kicks off automatically when games are ingested ("run on
   ingest").
3. Serverless processes **only the just-ingested games**, never drains the
   wider backlog.
4. Coexists with the pull-based pod model; bulk drains still use pods.
5. Serverless leverages the shared RunPod network volume (lc0 binary, BT4
   weights, Syzygy, lc0 tuning cache) so cold starts skip re-download and
   the ~9-min MinibatchSize calibration.
6. Separate hardware tiers: **CPU** serverless for Stockfish, **GPU**
   serverless for Lc0.
7. Failure-safe: a serverless failure must not lose work.

## Non-goals

- Replacing the pod/poll model (explicitly coexist, not replace).
- Reviving the original push-payload dispatch removed in #101 (the queue
  stays the single source of truth).
- TRT backend work (issue #119; this spec only notes the TRT engine cache
  must also live on the shared volume if/when #119 lands).
- The `--max-jobs` worker run-cap change (separate spec,
  `2026-05-15-worker-max-jobs-run-cap-design.md`).

## Design

### Trigger — post-commit, debounced

- During a Chess.com sync, after `enqueue_analysis_job` rows are committed,
  a Django `transaction.on_commit` hook collects the just-created
  `AnalysisJob`s grouped by engine.
- Dispatch happens **only** post-commit so a rolled-back ingest never wakes
  serverless (avoids the DB + RunPod dual-write trap).
- A short debounce window coalesces back-to-back syncs into at most one
  dispatch per engine per window.

### Dispatch — per engine, scoped payload

- One RunPod serverless request per engine that has new jobs:
  - Stockfish → `RUNPOD_STOCKFISH_ENDPOINT_ID` (CPU endpoint/image)
  - Lc0 → `RUNPOD_LC0_ENDPOINT_ID` (GPU endpoint/image)
- Request payload carries `{game_ids: [...]}` (the ingested games for that
  engine). Game-id granularity maps directly onto the existing
  `checkout(game_id=...)` primitive; no new server-side checkout path.
- The returned RunPod job id is recorded on each `AnalysisJob` via the
  existing `POST /api/v1/jobs/{id}/submit/` endpoint for observability
  (this endpoint already exists; #101 only removed the auto-dispatch, not
  the submit hook).
- Engine→endpoint→hardware is configured at RunPod endpoint-creation time
  (CPU vs GPU); the dispatch code only needs the correct endpoint IDs and
  per-engine grouping, which it already has.

### Handler — scoped pull, then exit

- The serverless handler reads `game_ids` from its invocation payload.
- For each id it calls `checkout(game_id=...)` (looped single-game
  checkouts — zero server-side change; chatty API is acceptable for these
  small batches), analyses, submits via the existing `/complete/`
  endpoint, then exits when its id list is exhausted.
- It never performs an unscoped `/checkout`, so unrelated backlog is never
  touched.

### Coexistence & failure safety

- Atomic checkout (existing `SELECT ... SKIP LOCKED`-equivalent locking)
  guarantees a pod and a serverless instance cannot double-process the same
  job; whichever claims it first wins, the other's scoped checkout simply
  finds it taken.
- If a serverless dispatch fails (endpoint down, quota, network), the jobs
  remain `pending` and a later pod run drains them — no work lost. This is
  the core reason for wake-and-scoped-pull over push-payload.

### Network volume strategy (per engine)

- **Lc0 GPU endpoint:** mounts the shared network volume containing the lc0
  binary, BT4 weights, Syzygy tablebases, and the lc0 tuning cache. Reusing
  the tuning cache skips the ~9-min calibration sweep on cold start. If
  issue #119 (TRT) lands, the TRT engine cache must also live on this
  volume.
- **Stockfish CPU endpoint:** needs effectively nothing from a network
  volume — the Stockfish binary ships in the image; Syzygy is optional.
  Default to no volume for Stockfish unless a shared eval cache is desired.
- **Constraints to honour:**
  - RunPod network volumes are **region-locked**: any endpoint sharing a
    volume must be created in that volume's region.
  - Serverless mounts the volume at `/runpod-volume`; pods use
    `/workspace`. The worker's `WLW_*` path configuration must be
    parameterised per environment rather than hardcoded.

### Eval cache concurrency

- Eval caches are already per-engine SQLite files (Stockfish #67, lc0 #65),
  so there is no cross-engine contention.
- The only hazard is a pod and one or more serverless instances writing the
  *same engine's* cache file concurrently on a shared volume. Resolution
  (pick during planning, default = first that holds):
  1. SQLite WAL mode + busy-timeout, tolerate occasional contention; or
  2. read-shared / write-local (serverless reads the volume copy, writes a
     local cache that is not persisted back); or
  3. Stockfish CPU endpoint uses no shared volume at all (sidesteps the
     issue for the high-frequency CPU path).

### Orphaned handler assessment

`services/lc0_worker/` and `services/stockfish_worker/` (handler.py,
Dockerfile, build-and-push scripts) exist but went stale after the #101
pivot. The implementation plan must assess revive-vs-rewrite of each
handler against the current `services/local_worker` analysis code
(`analysis/lc0.py`, `analysis/stockfish.py`, tuning, eval cache) and reuse
the shared analysis logic rather than forking it.

## Risks

- **Stale handlers diverge from current analysis code** — the biggest
  unknown; mitigated by the explicit revive-vs-rewrite assessment and
  reuse of `local_worker` analysis modules.
- **Region-lock mismatch** — CPU and GPU serverless endpoints plus the
  volume must be region-compatible; if not, the GPU endpoint cannot share
  the lc0 asset volume. Surface during endpoint provisioning.
- **Eval-cache corruption** under concurrent pod+serverless writes if no
  strategy is applied; mitigated by the eval-cache section above.
- **Cold-start latency floor:** Lc0 GPU cold start ≈ ~9s (CUDA + weights
  load) even with the volume mounted; Stockfish CPU cold start is
  near-instant. Acceptable for on-demand small batches; documented so
  expectations are set.
- **Debounce tuning:** too short → redundant invocations; too long →
  perceptible delay before analysis starts. Pick a sensible default
  (seconds, not minutes) during planning.

## Acceptance

- Ingesting games triggers, post-commit, a per-engine serverless dispatch
  carrying only those games' ids.
- Stockfish jobs run on a CPU serverless endpoint; Lc0 jobs run on a GPU
  serverless endpoint.
- The serverless handler processes exactly the dispatched games and exits;
  unrelated queued jobs are untouched.
- A killed/failed serverless invocation loses no work (jobs remain pending
  for a pod).
- Lc0 serverless cold start reuses the shared volume's tuning cache (no
  calibration sweep) and weights (no re-download).
- The pod/poll model continues to function unchanged for bulk drains.
