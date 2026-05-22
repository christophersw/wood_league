# Auto-enqueue fix — env toggles + reliable detection (#201)

**Date:** 2026-05-22
**Issue:** [#201](https://github.com/christophersw/wood_league/issues/201)
**Branch:** `issue/201-auto-enqueue-env-fix`

## Problem

Post-ingest auto-enqueue of `AnalysisJob` rows never fires.

1. **Toggles are DB-only.** `auto_enqueue_stockfish` / `auto_enqueue_lc0` live on the
   `SiteSettings` singleton (`core/models.py`), editable only via Django admin. We
   want them controllable at runtime on Railway via env vars.
2. **New-game detection never matches.** `sync_games.py` selects newly ingested
   games via `Game.objects.filter(created_at__gte=started_at)`, but the ingest
   subprocess writes through the legacy SQLAlchemy `Game` model
   (`app/storage/models.py`), which has no `created_at` column. Inserted rows get
   `created_at = NULL`, so the filter excludes them and `new_games` is always empty.

### Evidence (prod `wood_league_cron`, 2026-05-22)
- Run 13:36 inserted ~7,543 brand-new games → `auto-enqueued: stockfish=0 lc0=0`.
- Same run's opening-id step (`since=None`, no `created_at` filter) resolved all
  7,543 — the rows are present and visible to Django; only the `created_at` filter
  excludes them.
- `auto_enqueue_stockfish` defaults to `True`, so the toggle was not the blocker.

## Decisions

- **Toggles: env-only.** Remove the `SiteSettings` booleans entirely; read solely
  from env. (User decision.)
- **Defaults: both `False`.** Auto-enqueue is fully opt-in — nothing enqueues
  unless the env var is explicitly set on Railway. (User decision; note this is a
  behavior change from the old `SiteSettings` default of SF `True`.)
- **Detection: "lacking a satisfying job" sweep.** Drop the `created_at`-based time
  filter; enqueue any game with PGN that has no active job and no completed job at
  sufficient depth, reusing `enqueue_analysis_job`'s dedup. Self-healing; no
  dependency on the unstamped `created_at`. (User decision — option B.)

## Design

### 1. Env-only toggles (`config/settings.py`)
```python
AUTO_ENQUEUE_STOCKFISH = config("AUTO_ENQUEUE_STOCKFISH", default=False, cast=bool)
AUTO_ENQUEUE_LC0       = config("AUTO_ENQUEUE_LC0", default=False, cast=bool)
```
Set on the `wood_league_cron` Railway service to enable per engine at runtime.

### 2. Remove DB toggles
- Drop `auto_enqueue_stockfish` / `auto_enqueue_lc0` from `SiteSettings`
  (`core/models.py`) + Django migration (`RemoveField` ×2).
- Remove them from `core/admin.py` `list_display`.
- Update `core/tests/test_models.py` (currently asserts those fields).

### 3. Enqueue sweep (`ingest/management/commands/sync_games.py`)
Replace the broken `new_games = Game.objects.filter(created_at__gte=started_at)`
loop. For each engine, only when its env toggle is on:
```python
satisfying = AnalysisJob.objects.filter(
    game=OuterRef("pk"), engine=engine,
).filter(
    Q(status__in=_ACTIVE_STATUSES)
    | Q(status=AnalysisJob.STATUS_COMPLETED, depth__gte=depth)
)
candidates = Game.objects.filter(pgn__gt="").exclude(Exists(satisfying))
for game in candidates.iterator():
    if enqueue_analysis_job(game=game, engine=engine, depth=depth):
        count += 1
```
- `enqueue_analysis_job` remains the single source of truth (race-safe dedup +
  0-move PGN skip).
- The `Exists` pre-filter keeps steady-state runs cheap.
- `started_at` and the `created_at` filter are removed. The `created_at` column
  itself stays in place (out of scope to remove); it is simply no longer used for
  enqueue.
- `_ACTIVE_STATUSES` is imported/shared from `analysis.services.enqueue` to avoid
  duplicating the status list.

### 4. SystemEvent details
Change `new_games=N; sf_enqueued=X; lc0_enqueued=Y` →
`sf_enqueued=X; lc0_enqueued=Y` (the `new_games` count is no longer meaningful).

## Data flow
cron → `sync_games` → advisory lock → `run_sync` subprocess (upsert games) → on
success, per enabled engine: sweep unsatisfied games → `enqueue_analysis_job` →
move-time + opening-id post-steps → SystemEvent `completed` with enqueue counts →
release lock.

## Error handling
- Subprocess non-zero exit → SystemEvent `failed`, early return (unchanged).
- Per-game enqueue failures are isolated by `enqueue_analysis_job` (returns None on
  dedup/race/0-move).
- Both toggles off (the default) → no sweep runs → zero enqueued.

## Testing (TDD)
- `settings.AUTO_ENQUEUE_*` parse env correctly, including the `False` defaults.
- Sweep enqueues an unanalyzed game; **skips** a game with an active job and one
  with a completed job at ≥ requested depth (dedup).
- Engine toggle off → that engine enqueues nothing.
- 0-move PGN skipped.
- Re-run after enqueue → zero new jobs.
- Update `ingest/tests/test_sync_games_command.py`, `analysis/tests/test_enqueue.py`,
  `core/tests/test_models.py`.

## Out of scope
- Removing the `created_at` column.
- Any worker change (`services/local_worker/`).
