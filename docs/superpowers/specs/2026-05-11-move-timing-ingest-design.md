# Move-Timing Ingest — Design

**Status:** Draft for review
**Author:** Chris (with Claude)
**Date:** 2026-05-11
**Related:** Per-move chess.com timing data for quality-vs-time analyses

## Problem

Wood League stores Chess.com games and engine analysis, but throws away the per-move timing data embedded in every PGN. Without it we cannot answer:

- When do players actually make moves (hour of day, day of week, month)?
- Is there a quality difference by time of day, time of month, time on the clock?
- How does move quality correlate with think time or time-pressure?
- Does "rushed move" detection (very short think time before a blunder) signal anything useful?

The data is already present in `Game.pgn`. This spec adds a normalized table for per-move timing plus a few game-level columns, populated at ingest time and backfilled once across the existing corpus.

## Goals

1. Persist per-move "time spent" data for every Game whose PGN carries it.
2. Persist enough game-level time metadata to make per-move analyses joinable (start time UTC, time class, parsed time control).
3. Make per-move wall-clock submission timestamps **derivable on the fly** from `started_at_utc + cumsum(time_spent_ms)` — accurate to seconds for live games and to deciseconds for daily.
4. Keep clock parsing on the ingest path. No engine, no GPU, no per-job re-extraction.
5. Backfill the existing corpus with one idempotent management command.
6. Surface the data via simple SQL joins to `move_analysis` so chart/UI work later is straightforward.

## Non-goals

- **No retroactive vacation tracking.** Chess.com's API doesn't expose historical vacation usage; we accept whatever the PGN deltas tell us. (See "Future work" below.)
- **No per-move wall-clock-of-submission as a stored column.** It's derivable — storing it would just duplicate `started_at_utc + cumsum(time_spent_ms)` and require recomputation on every PGN re-parse.
- **No support for pre-2020 daily games' per-move data.** Those PGNs carry no `%clk` annotations. Game-level columns are still populated for them; the `GameMoveTime` table is left empty.
- **No worker-side parsing.** Clock data is ingest-side. Worker keeps doing engine work.
- **No live polling for move-submission attribution.** A separate spec, if pursued.

## Discovery: what chess.com actually gives us

(Findings from empirical testing during brainstorming, retained here so the parser implementation has a single authoritative reference.)

### Live games (bullet / blitz / rapid)

`%clk` in the PGN is **remaining clock after the move**, in seconds, standard PGN convention. Example for a 3+0 bullet game:

```
1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:03:00]}
2. Nc3 {[%clk 0:02:59.9]} 2... g6 {[%clk 0:02:57.5]}
```

Per-move time spent = `clk[N−2] − clk[N] + increment` (with per-side state, since `%clk` alternates White/Black).

### Daily games (2020+)

`%clk` in the public API is the **inter-move delay** (time from previous move's submission to this move's submission), but **rendered in deciseconds formatted as seconds**. To get true seconds, multiply by 10.

Verified empirically across multiple daily games:

| Game | Plies | API `sum(%clk)` × 10 | Wall-clock duration | Match |
|---|---|---|---|---|
| `erik` 2024/05 | 74 | 524,121 s | 524,144 s | 100.0% |
| `erik` 2024/06 | 61 | 429,063 s | 437,850 s | 98.0% |
| `erik` 2024/08 | 116 | 258,770 s | 258,797 s | 100.0% |
| `christophersw` 948193485 | 74 | 4,153,310 s | 4,212,442 s | 98.6% |

The small (≤2%) shortfall corresponds to the gap between the **last move's submission** and the game's official `end_time` (resignation event, timeout finalization, etc.). For per-move analysis this is correct — the last `time_spent_ms` represents the player's response time, not the time until the result was recorded.

The website's manual PGN download additionally includes a redundant `%timestamp <deciseconds>` tag with the same value. The published API drops `%timestamp` but keeps the equivalent `%clk` rendering. We rely on the API form only — no website scraping needed.

### Daily games (pre-2020)

PGN carries no `%clk` annotations. Per-move data is unavailable; game-level data still is.

### Wall-clock derivation per move

For both live and daily, `started_at_utc + cumsum(time_spent_ms[1..N])` reproduces the wall-clock submission time of move N. For live games this is exact to seconds; for daily games it's exact to deciseconds.

## Schema

### `games.Game` — new columns

```python
started_at_utc = models.DateTimeField(db_index=True)            # from JSON start_time
time_class = models.CharField(max_length=16, db_index=True)     # bullet/blitz/rapid/daily
time_control_base_s = models.IntegerField(null=True, blank=True)        # 180, 600, 604800, …
time_control_increment_s = models.IntegerField(null=True, blank=True)   # 0/5/…; NULL for daily
```

The existing `played_at` column (= chess.com's `end_time`) is kept for backward compatibility. `started_at_utc` is the new, more useful per-game timestamp.

`time_control` (raw string) is also kept untouched. The two parsed columns above are derived from it once at ingest.

Index `time_class` because it filters most per-move analyses (live vs daily handled differently in charts).

### `games.GameMoveTime` — new table

```python
class GameMoveTime(models.Model):
    game = models.ForeignKey("games.Game", on_delete=models.CASCADE, related_name="move_times")
    ply = models.IntegerField()                          # 1-based; ply 1 = White's first move
    time_spent_ms = models.IntegerField()                # universal — time this player took on this move
    clock_after_ms = models.IntegerField(null=True)      # live only; NULL for daily

    class Meta:
        db_table = "game_move_times"
        unique_together = [("game", "ply")]
        indexes = [
            models.Index(fields=["game", "ply"]),
        ]
```

Column rationale:

- `time_spent_ms` — universal signal, populated for every ply in both live and daily.
- `clock_after_ms` — live-only. Enables "blunders under 5s remaining" / time-pressure analyses. NULL for daily because there's no equivalent shared-clock concept.
- Milliseconds throughout: live games carry decisecond precision in `%clk`; daily carries decisecond too. Storing as `IntegerField(ms)` is a clean integer representation. (Postgres int4 ranges to ~24 days in ms — fine for live, fine for daily per-move deltas up to ~24 days. Per-move daily deltas in our corpus never approach that.)
- No `time_class` denorm on `GameMoveTime` — join to `Game.time_class` when needed.

### Joins to existing data

`MoveAnalysis` is keyed on `(analysis, ply)` where `analysis` is `GameAnalysis(game=…)`. To join engine evaluation to clock data:

```sql
SELECT m.cpl, m.classification, t.time_spent_ms, t.clock_after_ms,
       g.time_class, g.started_at_utc
FROM move_analysis m
JOIN game_analysis a ON m.analysis_id = a.id
JOIN games g ON a.game_id = g.id
JOIN game_move_times t ON t.game_id = g.id AND t.ply = m.ply
WHERE g.time_class = 'daily';
```

Simple and indexable.

## Parser

New module: `services/app/games/clock_parser.py`. Pure Python. No Django imports. Unit-testable in isolation.

```python
@dataclass(frozen=True)
class MoveTime:
    ply: int
    time_spent_ms: int
    clock_after_ms: int | None   # None for daily

def parse_move_times(pgn: str, *, time_class: str) -> list[MoveTime]:
    """Parse per-move time data from a chess.com PGN.

    Returns [] if no %clk annotations are present (pre-2020 daily games).
    For live games, computes time_spent from %clk deltas with per-side state.
    For daily, treats %clk values as deciseconds (multiplies by 10) to get
    inter-move-delay-in-seconds, then converts to ms.

    Args:
        pgn: Full PGN string.
        time_class: 'bullet' | 'blitz' | 'rapid' | 'daily'. Drives parsing mode.

    Returns:
        list[MoveTime], one entry per ply that carried a %clk annotation.
    """
```

Implementation notes:

- Regex `\d+\.+\s*(\S+)\s*\{\[%clk ([0-9:.]+)\]\}` matched per-move.
- Detect side from ply parity (odd = White, even = Black).
- For live: maintain a per-side previous-clock state. `time_spent_ms = (prev_clk + increment - current_clk) * 1000`. For move 1 of each side, `prev_clk = base + increment`.
- For daily: `time_spent_ms = clk_seconds * 10 * 1000` (decisecond reading × ms-per-decisecond).
- Negative `time_spent_ms` (clock anomalies, server-side adjustments) → clamp to 0 and log a warning. These are rare but observed in some games.

Time-control parsing: `services/app/games/time_control_parser.py`.

```python
def parse_time_control(tc: str) -> tuple[int | None, int | None]:
    """Parse a chess.com time_control string.

    Returns (base_seconds, increment_seconds). Returns (None, None) for
    unrecognised formats so the column ends up NULL.

    Examples:
        "180"       -> (180, 0)
        "180+0"     -> (180, 0)
        "600+5"     -> (600, 5)
        "1/604800"  -> (604800, None)   # daily: N seconds per move, no increment
    """
```

## Ingest integration

Current path: Django cron service runs `manage.py sync_games` → acquires advisory lock → shells out to `app/ingest/run_sync.py` (SQLAlchemy ingest) → writes to the shared `games` table.

Three edits:

1. **SQLAlchemy `Game` mirror class** (`services/app/app/storage/models.py`): add columns matching the Django model so the SQLAlchemy session can set them. Columns alone — no relationships, no methods. The Django model remains the source of truth for migrations.
2. **`sync_service._upsert_game`**: after computing `played_at` (= `end_time`), also compute `started_at_utc` (= `start_time`), parse `time_control` into base+increment, and read `time_class` directly from the JSON. Write all four to the row.
3. **After the SQLAlchemy upsert commits**, the Django `sync_games` command runs a per-game post-step that calls `parse_move_times(game.pgn, time_class=game.time_class)` and bulk-creates `GameMoveTime` rows.

The post-step lives in the Django command, not the SQLAlchemy service, because:

- `GameMoveTime` will only exist as a Django model (no SQLAlchemy mirror).
- The SQLAlchemy service is already on borrowed time; we don't want to extend it.
- Failures parsing one game's clock data should not roll back the game itself.

Failure isolation: each `parse_move_times` call is wrapped in try/except. On exception, the game row is committed without `GameMoveTime` rows and a warning is logged to `SystemEvent`. The backfill command can retry later.

Idempotency: on re-ingest of an existing game, `GameMoveTime` rows for that game are deleted and rewritten. Cheap, since per-game ply count is ≤ ~300.

## Backfill

New management command: `services/app/games/management/commands/backfill_move_times.py`.

Behavior:

- Iterates every `Game` row with non-empty `pgn`.
- Skips rows that already have `GameMoveTime` rows AND non-null `started_at_utc` AND non-null `time_class` (idempotent — safe to re-run).
- For each game: parse headers for `started_at_utc` if missing, parse `time_control` if `time_control_base_s` missing, parse move times.
- Bulk-create `GameMoveTime` rows in transactions of 500 games at a time (Postgres bulk-insert friendly).
- Logs a `SystemEvent` summary at end: total processed, rows written, failures.

CLI args:

```
manage.py backfill_move_times              # all games
manage.py backfill_move_times --dry-run    # parse + report, no writes
manage.py backfill_move_times --limit 100  # for testing
```

Estimated cost: parsing one 80-ply PGN takes <1ms; even 100k games is under a few minutes of CPU. No external API calls — pure local parse.

## Testing

### Unit tests (new)

- `tests/test_clock_parser.py`
  - Live game: full PGN → expected ply-by-ply `time_spent_ms` / `clock_after_ms`.
  - Live game with increment: verify `time_spent` formula respects increment.
  - Daily game: full PGN → values 10× the `%clk` seconds, `clock_after_ms = None`.
  - Pre-2020 daily (no `%clk`): returns `[]`.
  - Negative computed time-spent (clock anomaly): clamps to 0, logs warning.
  - Malformed PGN: raises a typed error, doesn't return wrong data silently.
- `tests/test_time_control_parser.py`
  - Live formats: `"180"`, `"180+0"`, `"600+5"`, `"30+15"`.
  - Daily format: `"1/604800"`, `"1/259200"`.
  - Unknown: `"garbage"` → `(None, None)`.

### Integration tests

- `ingest/tests/test_sync_games_command.py` — add a test that verifies a freshly-synced game has its `GameMoveTime` rows populated and `started_at_utc` / `time_class` set.
- A small backfill integration test that runs `backfill_move_times --limit 5` against a fixture of mixed live and daily games and asserts row counts + sums.

### Verification queries

After backfill, two sanity checks run as part of the backfill summary:

1. For each daily game with `GameMoveTime` rows, `sum(time_spent_ms) ≤ (end_time − start_time) * 1000`. Flag any violations.
2. For each live game, `last_clock_after_ms ≥ 0` (no clock running into negative).

## Open questions

These are flagged so reviewers can weigh in before implementation; defaults are chosen if not raised.

1. **Storage size estimate.** Average ~80 plies per game × 100k games = 8M rows. Each row ≈ 40 bytes raw. ~320 MB before indexes. Comfortable on Railway Postgres but worth knowing.
2. **`game_move_times` retention.** Tied to game lifecycle via `on_delete=CASCADE`. If we ever delete a game, its move-time rows go with it. Same model as `MoveAnalysis`.
3. **No fancier "side" denorm.** Could add a `side` column to `GameMoveTime` for query convenience, but it's derivable from `ply % 2`. YAGNI: skip until a query proves it's needed.

## Future work (out of scope for this spec)

- **Forward-only daily polling for move-submission ground truth.** Build a `MoveObservation` table populated from `pub/player/{user}/games` (current games) polling. Get wall-clock-of-move-submission to within poll-interval accuracy. Useful if we want to verify our derivation or detect vacation directly. Separate spec.
- **Move-time fingerprinting / cheating detection.** Once `GameMoveTime` exists, derived features like "implausibly even spacing", "consistent <5s moves in complex positions" become possible. Separate spec.
- **Charts and dashboards.** Pre-aggregated views ("avg ACPL by hour of day") for the frontend. Separate spec; depends on this one shipping.
