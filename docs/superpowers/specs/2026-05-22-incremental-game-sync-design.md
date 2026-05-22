# Incremental Chess.com game sync — design (#204)

**Date:** 2026-05-22
**Issue:** [#204](https://github.com/christophersw/wood_league/issues/204)
**Status:** Approved design, pre-implementation

## Problem

The `sync_games` management command runs on a Railway cron **every 15 minutes**.
On every run it re-downloads and re-upserts *all* games within a fixed
`ingest_month_limit` window (default **24 months**) for *every* club member,
even though almost all of those games are already in the database. This is a
large amount of needless HTTP fetching and PGN re-parsing for unchanged games.

### Current flow (live cron path)

`sync_games` command → subprocess `services/app/app/ingest/run_sync.py`
→ `ChessComSyncService.sync_player()` in
`services/app/app/ingest/sync_service.py`.

In `sync_player()`:

1. `ChessComClient.get_archives(username)` returns *every* monthly archive URL
   the player has ever had (no Chess.com-side cap; back to account creation).
2. Archives are filtered only by `_archive_in_scope()` → `ingest_month_limit`,
   a fixed N-month lookback — **not** by what is already loaded.
3. For each in-scope archive, *all* games are fetched and `_upsert_game()` is
   called for each. Already-loaded games take the `"updated"` path and are
   re-parsed (PGN, opening, result) and re-written every run.

`ingest_month_limit` is env-driven (`INGEST_MONTH_LIMIT`, default 24) via
pydantic `Settings` and Django `config/settings.py`, settable on Railway.

## Goal

Only fetch and process games that are **newer** than what is already loaded,
while preserving a way to force a full re-ingest when needed.

## Approach

**Per-player watermark, watermark-only** (no HTTP ETag/conditional-GET layer —
that was considered and deferred as unnecessary complexity for marginal extra
savings on the single current-month re-fetch).

### 1. Watermark

New helper `_player_watermark(session, player) -> datetime | None`:

- Returns `max(Game.played_at)` over that player's games, joined via
  `GameParticipant.player_id == player.id`.
- Returns `None` when the player has no games yet.

`Game.played_at` is set from the Chess.com `end_time`
(`datetime.fromtimestamp(end_time, UTC)`), so the watermark is directly
comparable to each payload's `end_time`.

**Timezone handling (explicit footgun):** `played_at` is stored without tz info
and read back as a naive datetime. The helper normalizes the watermark to a
single UTC **epoch int** so all comparisons are int-vs-int against the payload
`end_time`. No naive-vs-aware datetime comparison anywhere.

### 2. Archive selection — skip whole months before any fetch

- **Has watermark and not `--full`:** keep only archives whose
  `(year, month) >= watermark's (year, month)`. Strictly-older months are
  dropped *before any HTTP fetch* — this is the primary saving (≈23 of 24
  months eliminated). `ingest_month_limit` is **not** applied in this branch.
- **No watermark (new player) or `--full`:** fall back to the existing
  `_archive_in_scope()` / `ingest_month_limit` behavior. The env-driven month
  limit thus becomes purely the **first-sync backfill depth** for players with
  no games yet.

### 3. Per-game skip — handles the watermark's own month

Within each fetched archive, skip any game whose `end_time < watermark_epoch`.

- Strict `<` (not `<=`): the boundary game(s) sharing the exact watermark second
  are harmlessly re-upserted each run (cheap, idempotent), which avoids missing
  a genuinely new game that happens to share that same second.
- Skipped before `_upsert_game()`, so only genuinely new games are parsed/written.

### 4. `--full` escape hatch, wired end to end

- `sync_player(username, *, full: bool = False, progress_callback=None)` — the
  new kwarg bypasses both the month gate (§2) and the per-game skip (§3).
- `run_sync.py` gains a `--full` argparse flag, passed through to `sync_player`.
- `sync_games` command: **remove the dead `--days` flag** (today it is parsed
  but never reaches the subprocess, so it is silently ignored) and add
  `--full`, threaded into the subprocess command built in `_do_sync`.

`--full` is the documented way to re-pull history after ingest logic changes or
to recover a game Chess.com corrected after we first loaded it.

### 5. Observability

Add an `archives_skipped` counter to `SyncStats` and surface it in the run
summary and the `game_sync` `SystemEvent` details, so cron logs show how many
months were skipped and confirm the optimization is working in production.

## Components touched

| File | Change |
|------|--------|
| `services/app/app/ingest/sync_service.py` | `_player_watermark`, archive month gate, per-game skip, `full` kwarg, `archives_skipped` on `SyncStats` |
| `services/app/app/ingest/run_sync.py` | `--full` argparse flag, pass through |
| `services/app/ingest/management/commands/sync_games.py` | remove `--days`, add `--full`, thread into subprocess; include `archives_skipped` in `SystemEvent` details |

Stale copies under `packages/shared/wood_league_shared/ingest/` and
`services/stockfish_worker/stockfish_pipeline/ingest/` are **not** on the cron
path and are left unchanged ("stay local").

## Testing (TDD)

- `_player_watermark`: returns max `played_at` for the player; `None` when the
  player has no games.
- Month gate: archives for months strictly older than the watermark month are
  never requested from `ChessComClient` (assert via a mocked client).
- Per-game skip: games with `end_time < watermark` are not upserted; newer ones
  are.
- New player (no watermark) → full `ingest_month_limit` backfill still occurs.
- `--full` bypasses the watermark and re-pulls already-loaded games.
- `archives_skipped` is counted and reported.
- Command level: `--full` reaches the subprocess; `--days` is removed.

## Edge cases

- **New club member with old games:** no watermark → backfills within
  `ingest_month_limit`. ✓
- **Game corrected on Chess.com after load:** missed by the fast path by
  design; `--full` is the escape hatch. ✓
- **Empty / move-less games:** still dropped at `_upsert_game()` (issue #18),
  unchanged. ✓
- **Same-second boundary games:** strict `<` re-upserts them harmlessly rather
  than risk skipping a new one. ✓

## Out of scope

- HTTP ETag / `If-None-Match` conditional GETs (avoids the single current-month
  re-fetch) — deferred; would need per-archive ETag persistence.
- Changing the default `INGEST_MONTH_LIMIT` value.
- Touching the non-cron duplicate sync_service copies.
