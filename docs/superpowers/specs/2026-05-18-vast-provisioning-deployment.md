# vast.ai Reconcile — Deployment Note (Sub-project A)

**Cron command:** `python manage.py reconcile_vast_analysis`
**Schedule:** every 45 minutes (`*/45 * * * *`)
**Where:** a Railway **cron service** in the same project as the app,
sharing the app's Postgres. Railway cron schedule is set on the service
in the Railway dashboard (Settings → Cron Schedule), not in
`services/app/railway.toml` (that file is the web service).

**Required env on the cron service** (in addition to the shared DB vars):
- `VAST_ENABLED=true`
- `VAST_API_KEY=<secret>` (never placed on a rented box)
- `VAST_TEMPLATE_HASH=<current release template hash>` (re-point per
  worker release, e.g. when the image tag bumps)
- `VAST_CAMPAIGN_ID=<campaign id passed through to the worker>`
- Optional overrides: `VAST_OFFER_GPU_NAME` (default `L40S`),
  `VAST_OFFER_MAX_DPH` (default `1.50`), `VAST_MAX_JOBS` (default `100`),
  `VAST_HARD_DEADLINE_HOURS` (default `6`),
  `VAST_WORKER_STALE_MINUTES` (default `15`).

**Worker template prerequisite:** the vast template referenced by
`VAST_TEMPLATE_HASH` must run the pull worker honoring `WL_CAMPAIGN_ID`,
`WLW_MAX_JOBS`, and reporting `WorkerHeartbeat` (existing worker behaviour;
no worker change in this sub-project). Per-run `env` (campaign, max jobs,
schedule id) is merged over the template env by vast at create time.

**Manual trigger:** insert a `pending` row in Django admin →
*Analysis Schedules* (or `AnalysisSchedule.objects.create()`); the next
cron tick picks it up. No web button (by design).

**Safety recap:** ≤1 instance ever live; a drained box (detected via the
launched worker's `WorkerHeartbeat` going stale for
`VAST_WORKER_STALE_MINUTES`) is destroyed within ≤45 min; `hard_deadline`
is the absolute cost ceiling; all state in Postgres so a cron
crash/redeploy self-heals next tick. On a no-offer tick nothing is
created (no DB row, no box); the schedule stays `pending` and is
retried next tick.
