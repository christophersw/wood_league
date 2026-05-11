# Move-Timing Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-move clock data from chess.com PGNs into a new `GameMoveTime` table at ingest time, plus four time-related columns on `Game`, with a one-shot backfill for the existing corpus.

**Architecture:** Two new pure-Python parser modules in the `games` Django app (no Django imports → unit-testable in isolation). New Django model + migration for `GameMoveTime`. SQLAlchemy mirror class extended so the legacy ingest service can write the new `Game` columns. The Django `sync_games` management command runs a post-step that parses PGNs and bulk-inserts move-time rows. A new `backfill_move_times` management command sweeps the existing corpus idempotently.

**Tech Stack:** Django 5 ORM, SQLAlchemy 2, Postgres, pytest (with Django settings via `manage.py test`). Tests assume Postgres at `postgres://christopherwebster@localhost:5432/wood_league` with `SECRET_KEY=test-secret DEBUG=true` (matches the pattern used in PR #21).

**Spec:** `docs/superpowers/specs/2026-05-11-move-timing-ingest-design.md` (commit `bee0d70`)

---

## File structure

**Create:**
- `services/app/games/clock_parser.py` — Pure-Python PGN `%clk` parser. Two modes: live (clock deltas) and daily (deciseconds × 10).
- `services/app/games/time_control_parser.py` — Pure-Python `time_control` string parser. Returns `(base_seconds, increment_seconds)`.
- `services/app/games/tests/__init__.py` — Empty package init.
- `services/app/games/tests/test_clock_parser.py` — Unit tests for the clock parser.
- `services/app/games/tests/test_time_control_parser.py` — Unit tests for the time-control parser.
- `services/app/games/tests/test_models.py` — Tests for `GameMoveTime` model behavior and `Game` new columns.
- `services/app/games/migrations/0004_game_time_fields_and_move_times.py` — Django migration adding 4 Game columns + new `GameMoveTime` table.
- `services/app/games/management/__init__.py` — Empty package init (if not present).
- `services/app/games/management/commands/__init__.py` — Empty package init.
- `services/app/games/management/commands/backfill_move_times.py` — One-shot backfill management command.
- `services/app/games/tests/test_backfill_move_times.py` — Integration test for the backfill command.

**Modify:**
- `services/app/games/models.py` — Add 4 new columns to `Game`; add `GameMoveTime` model.
- `services/app/app/storage/models.py` — Mirror the 4 new `Game` columns on the SQLAlchemy class (no relationships, no `GameMoveTime` mirror).
- `services/app/app/ingest/sync_service.py` — Set `started_at_utc`, `time_class`, `time_control_base_s`, `time_control_increment_s` in `_upsert_game`. Return the game id (already does).
- `services/app/ingest/management/commands/sync_games.py` — After the SQLAlchemy subprocess completes, walk newly-touched games and bulk-create `GameMoveTime` rows via the Django ORM.
- `services/app/ingest/tests/test_sync_games_command.py` — Assert post-sync rows exist for one freshly-synced game.

**Tests for files with no existing test coverage** (clock_parser, time_control_parser, GameMoveTime model, backfill command) live alongside the source in `services/app/games/tests/`.

---

## Test commands

Two environment variables required for every server-side test run:

```bash
SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league
```

Path is `services/app/`. Run from that directory. `manage.py test` auto-creates a test DB; `--keepdb` reuses it for speed across tasks.

---

## Tasks

### Task 1: Time-control parser

**Files:**
- Create: `services/app/games/time_control_parser.py`
- Create: `services/app/games/tests/__init__.py`
- Create: `services/app/games/tests/test_time_control_parser.py`

- [ ] **Step 1: Create the test package init.**

Create `services/app/games/tests/__init__.py` with empty content.

- [ ] **Step 2: Write failing tests.**

Create `services/app/games/tests/test_time_control_parser.py`:

```python
"""
Title: test_time_control_parser.py — Tests for chess.com time_control parsing.
Description:
    Verifies parse_time_control covers live formats (with/without increment),
    daily formats (1/N seconds), and gracefully returns (None, None) for
    unknown input.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from games.time_control_parser import parse_time_control


def test_live_no_increment():
    assert parse_time_control("180") == (180, 0)


def test_live_explicit_zero_increment():
    assert parse_time_control("180+0") == (180, 0)


def test_live_with_increment():
    assert parse_time_control("600+5") == (600, 5)


def test_live_long_with_increment():
    assert parse_time_control("1800+30") == (1800, 30)


def test_daily_three_days():
    assert parse_time_control("1/259200") == (259200, None)


def test_daily_one_week():
    assert parse_time_control("1/604800") == (604800, None)


def test_unknown_returns_nones():
    assert parse_time_control("garbage") == (None, None)


def test_empty_returns_nones():
    assert parse_time_control("") == (None, None)
```

- [ ] **Step 3: Run tests to verify they fail.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_time_control_parser --keepdb
```

Expected: ImportError / module-not-found, FAIL.

- [ ] **Step 4: Implement the parser.**

Create `services/app/games/time_control_parser.py`:

```python
"""
Title: time_control_parser.py — Parse chess.com time_control strings
Description:
    Pure helper that converts chess.com's `time_control` string field
    into structured (base_seconds, increment_seconds) values. Returns
    (None, None) for unrecognised input so callers can store NULLs.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from __future__ import annotations


def parse_time_control(time_control: str) -> tuple[int | None, int | None]:
    """Parse a chess.com `time_control` string.

    Args:
        time_control: Raw string from the chess.com API. Known shapes:
            - "180"        — live, 3 minute, no increment
            - "180+0"      — live, 3 minute, explicit zero increment
            - "600+5"      — live, 10 minute with 5s increment
            - "1/259200"   — daily, one move per 259200 seconds (3 days)

    Returns:
        Tuple of (base_seconds, increment_seconds). For daily formats the
        base is the per-move budget and increment is None. For unknown or
        empty input, returns (None, None).
    """
    if not time_control:
        return (None, None)
    if time_control.startswith("1/"):
        try:
            return (int(time_control[2:]), None)
        except ValueError:
            return (None, None)
    if "+" in time_control:
        base_str, inc_str = time_control.split("+", 1)
        try:
            return (int(base_str), int(inc_str))
        except ValueError:
            return (None, None)
    try:
        return (int(time_control), 0)
    except ValueError:
        return (None, None)
```

- [ ] **Step 5: Run tests to verify they pass.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_time_control_parser --keepdb
```

Expected: 8 passed.

- [ ] **Step 6: Bandit + ruff.**

```bash
ruff check services/app/games/time_control_parser.py services/app/games/tests/test_time_control_parser.py
bandit -ll services/app/games/time_control_parser.py
```

Expected: ruff "All checks passed!", bandit no medium/high issues.

- [ ] **Step 7: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/games/time_control_parser.py services/app/games/tests/__init__.py services/app/games/tests/test_time_control_parser.py && git commit -m "feat(games): parse chess.com time_control strings (issue #24)

Adds time_control_parser.parse_time_control which converts the raw
chess.com 'time_control' string into (base_seconds, increment_seconds)
tuples. Handles live (180, 180+0, 600+5) and daily (1/N) formats.
Returns (None, None) for unknown shapes so callers can store NULLs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Clock parser — data class + live games

**Files:**
- Create: `services/app/games/clock_parser.py`
- Create: `services/app/games/tests/test_clock_parser.py`

- [ ] **Step 1: Write failing tests for the live path.**

Create `services/app/games/tests/test_clock_parser.py`:

```python
"""
Title: test_clock_parser.py — Tests for chess.com PGN %clk parsing.
Description:
    Verifies parse_move_times for live games (clock-delta math) and daily
    games (deciseconds-as-seconds scaling), plus edge cases like empty
    PGNs, malformed input, and clock anomalies that produce negative
    deltas.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from games.clock_parser import MoveTime, parse_move_times


_LIVE_PGN_3_PLUS_0 = """[Event "Live Chess"]
[TimeControl "180"]

1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:02:58]} 2. Nf3 {[%clk 0:02:55]} 2... d6 {[%clk 0:02:50]} 1-0
"""


def test_live_3_plus_0_time_spent_per_ply():
    """3-minute game with no increment: time spent on each move = previous clk - current clk."""
    result = parse_move_times(
        _LIVE_PGN_3_PLUS_0, time_class="blitz",
        time_control_base_s=180, time_control_increment_s=0,
    )
    assert len(result) == 4
    # Move 1 (White): started with 180s, played e4 with 180s left -> spent 0s
    assert result[0] == MoveTime(ply=1, time_spent_ms=0, clock_after_ms=180_000)
    # Move 2 (Black): started with 180s, played c5 with 178s left -> spent 2s
    assert result[1] == MoveTime(ply=2, time_spent_ms=2_000, clock_after_ms=178_000)
    # Move 3 (White): previous White clk was 180s, now 175s -> spent 5s
    assert result[2] == MoveTime(ply=3, time_spent_ms=5_000, clock_after_ms=175_000)
    # Move 4 (Black): previous Black clk was 178s, now 170s -> spent 8s
    assert result[3] == MoveTime(ply=4, time_spent_ms=8_000, clock_after_ms=170_000)


_LIVE_PGN_5_PLUS_3 = """[Event "Live Chess"]
[TimeControl "300+3"]

1. e4 {[%clk 0:05:01]} 1... e5 {[%clk 0:05:03]} 1-0
"""


def test_live_with_increment_added_back():
    """Increment is added to previous-clk before subtracting current-clk.

    White starts with 300s, plays e4, gets +3s for the move -> clk shows 301.
    Time spent = (300 + 3) - 301 = 2s.
    """
    result = parse_move_times(
        _LIVE_PGN_5_PLUS_3, time_class="rapid",
        time_control_base_s=300, time_control_increment_s=3,
    )
    assert result[0].time_spent_ms == 2_000
    assert result[1].time_spent_ms == 0  # Black played instantly: 300 + 3 = 303 -> shown 303 ... actually
    # Actually let me recompute: 1... e5 {[%clk 0:05:03]} -> Black has 303s left.
    # Black's previous clk was 300 (base) + 3 (increment) = 303. Now 303 -> spent 0.
```

Wait — re-check the increment formula. Increment is added **after** the move. So before move N, Black's clock is `prev_clk_after_N-2`. After playing, Black's clock is `prev_clk_after_N-2 - time_spent + increment` ... but `%clk` is shown post-move post-increment.

For move 1 by either side, "prev clk" = `base + increment` (because the increment is conceptually added at the start of each move's clock for the formula to work cleanly). Standard PGN convention.

- [ ] **Step 2: Refine the increment test to match the formula in the spec.**

Replace the `test_live_with_increment_added_back` test with this corrected version (the formula is `time_spent = (prev_clk + increment) - current_clk`, and "prev_clk" for the first move per side is `base`):

```python
def test_live_with_increment_added_back():
    """Increment is added to previous-clk before subtracting current-clk.

    For 5+3 starting clock: each side starts with 300s. After move 1, the
    %clk reflects (300 - time_spent + 3). White's 0:05:01 = 301s means
    time_spent = 300 + 3 - 301 = 2s. Black's 0:05:03 = 303s means
    time_spent = 300 + 3 - 303 = 0s.
    """
    result = parse_move_times(
        _LIVE_PGN_5_PLUS_3, time_class="rapid",
        time_control_base_s=300, time_control_increment_s=3,
    )
    assert result[0] == MoveTime(ply=1, time_spent_ms=2_000, clock_after_ms=301_000)
    assert result[1] == MoveTime(ply=2, time_spent_ms=0, clock_after_ms=303_000)
```

- [ ] **Step 3: Add a clock-anomaly test (negative delta clamps to 0).**

Append to the same test file:

```python
_LIVE_PGN_ANOMALY = """[Event "Live Chess"]
[TimeControl "180"]

1. e4 {[%clk 0:03:01]} 1-0
"""


def test_live_clock_anomaly_clamps_to_zero():
    """If %clk > previous clk + increment (server hiccup / reconnect), clamp to 0.

    White starts with 180s, no increment, plays e4 with 181s left.
    Naive math gives -1s; we clamp to 0 rather than reporting impossible times.
    """
    result = parse_move_times(
        _LIVE_PGN_ANOMALY, time_class="bullet",
        time_control_base_s=180, time_control_increment_s=0,
    )
    assert result[0].time_spent_ms == 0
```

- [ ] **Step 4: Run tests to verify they fail.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_clock_parser --keepdb
```

Expected: ImportError, all tests fail.

- [ ] **Step 5: Implement the parser (live path + scaffolding).**

Create `services/app/games/clock_parser.py`:

```python
"""
Title: clock_parser.py — Parse %clk annotations from chess.com PGNs
Description:
    Pure-Python parser that extracts per-move time data from chess.com
    PGN move comments. Two modes:

    - Live (bullet/blitz/rapid): %clk is remaining clock; time_spent
      is computed as (previous_clk + increment) - current_clk with
      per-side state.
    - Daily: %clk values are deciseconds rendered as seconds; the
      already-rendered value × 10 equals the inter-move delay in
      seconds (verified empirically — see the spec at
      docs/superpowers/specs/2026-05-11-move-timing-ingest-design.md).

    Negative time deltas (server hiccups, reconnects) are clamped to 0.
    Pre-2020 daily games with no %clk annotations return []; the caller
    can persist game-level fields without per-ply rows.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MoveTime:
    """Parsed per-move timing for a single ply.

    Attributes:
        ply: 1-based ply number. ply=1 is White's first move.
        time_spent_ms: Time the player took on this move, in milliseconds.
            Always populated.
        clock_after_ms: Remaining clock after this move, in milliseconds.
            Populated only for live games; None for daily.
    """

    ply: int
    time_spent_ms: int
    clock_after_ms: int | None


_MOVE_RE = re.compile(
    r"""
    (?P<move_no>\d+)        # move number
    (?P<dots>\.+)\s*        # one or three dots
    (?P<san>\S+)\s*         # move SAN
    \{\[\%clk\s+
    (?P<clk>[0-9:.]+)       # H:MM:SS(.ds)
    \]
    """,
    re.VERBOSE,
)


def _clk_to_ms(clk: str) -> int:
    """Convert a `H:MM:SS(.ds)` clock string to milliseconds."""
    h, m, s = clk.split(":")
    return int(int(h) * 3600_000 + int(m) * 60_000 + float(s) * 1000)


def _parse_live(
    matches: list[re.Match],
    base_ms: int,
    increment_ms: int,
) -> list[MoveTime]:
    """Live-game parse: clock deltas with per-side state."""
    prev_clk_white = base_ms
    prev_clk_black = base_ms
    out: list[MoveTime] = []
    for m in matches:
        move_no = int(m.group("move_no"))
        dots = m.group("dots")
        is_black = len(dots) == 3
        ply = move_no * 2 - (0 if is_black else 1)
        clk_after_ms = _clk_to_ms(m.group("clk"))
        prev = prev_clk_black if is_black else prev_clk_white
        spent_ms = (prev + increment_ms) - clk_after_ms
        if spent_ms < 0:
            spent_ms = 0
        if is_black:
            prev_clk_black = clk_after_ms
        else:
            prev_clk_white = clk_after_ms
        out.append(MoveTime(ply=ply, time_spent_ms=spent_ms, clock_after_ms=clk_after_ms))
    return out


def _parse_daily(matches: list[re.Match]) -> list[MoveTime]:
    """Daily-game parse: %clk × 10 = inter-move delay in seconds."""
    out: list[MoveTime] = []
    for m in matches:
        move_no = int(m.group("move_no"))
        dots = m.group("dots")
        is_black = len(dots) == 3
        ply = move_no * 2 - (0 if is_black else 1)
        clk_seconds_decisecond_units = _clk_to_ms(m.group("clk")) / 1000.0
        time_spent_ms = int(clk_seconds_decisecond_units * 10 * 1000)
        out.append(MoveTime(ply=ply, time_spent_ms=time_spent_ms, clock_after_ms=None))
    return out


def parse_move_times(
    pgn: str,
    *,
    time_class: str,
    time_control_base_s: int | None = None,
    time_control_increment_s: int | None = None,
) -> list[MoveTime]:
    """Parse per-move timing from a chess.com PGN.

    Args:
        pgn: Full PGN string.
        time_class: One of 'bullet', 'blitz', 'rapid', 'daily'. Drives the
            parse mode.
        time_control_base_s: Base seconds. Required for live games (used as
            "previous clock" for each side's first move). Ignored for daily.
        time_control_increment_s: Per-move increment in seconds. Defaults to
            0 for live if not supplied. Ignored for daily.

    Returns:
        A list of MoveTime entries, one per ply that carried a %clk
        annotation. Empty list if no %clk annotations are present
        (pre-2020 daily games).
    """
    matches = list(_MOVE_RE.finditer(pgn))
    if not matches:
        return []
    if time_class == "daily":
        return _parse_daily(matches)
    base_ms = (time_control_base_s or 0) * 1000
    increment_ms = (time_control_increment_s or 0) * 1000
    return _parse_live(matches, base_ms, increment_ms)
```

- [ ] **Step 6: Run live tests to verify they pass.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_clock_parser --keepdb
```

Expected: 3 passed.

- [ ] **Step 7: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/games/clock_parser.py services/app/games/tests/test_clock_parser.py && git commit -m "feat(games): clock_parser scaffold + live-game %clk parsing (issue #24)

New pure-Python clock_parser.parse_move_times handles live games via
per-side clock-delta math. Increment is added back into 'previous clk'
before subtracting the current %clk. Negative deltas (server hiccups)
clamp to 0. Daily handling is stubbed; tests for it follow in the next
commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Clock parser — daily games + edge cases

**Files:**
- Modify: `services/app/games/tests/test_clock_parser.py`

- [ ] **Step 1: Add failing tests for daily games and edge cases.**

Append to `services/app/games/tests/test_clock_parser.py`:

```python
# Real PGN fragment from chess.com API (game 948193485, daily 1/604800).
# Each API %clk value × 10 gives the actual inter-move delay in seconds.
_DAILY_API_PGN = """[Event "Let's Play!"]
[TimeControl "1/604800"]

1. e4 {[%clk 0:00:00.5]} 1... c6 {[%clk 0:30:05.2]} 2. d4 {[%clk 0:05:21.7]} 1-0
"""


def test_daily_clk_treated_as_deciseconds_scaled():
    """In the API daily PGN, %clk seconds × 10 = real inter-move delay seconds.

    Move 1 e4: %clk 0:00:00.5 = 0.5s api -> 5000ms real spent.
    Move 2 c6: %clk 0:30:05.2 = 1805.2s api -> 18,052,000ms real spent.
    Move 3 d4: %clk 0:05:21.7 = 321.7s api -> 3,217,000ms real spent.
    """
    result = parse_move_times(_DAILY_API_PGN, time_class="daily")
    assert len(result) == 3
    assert result[0] == MoveTime(ply=1, time_spent_ms=5_000, clock_after_ms=None)
    assert result[1] == MoveTime(ply=2, time_spent_ms=18_052_000, clock_after_ms=None)
    assert result[2] == MoveTime(ply=3, time_spent_ms=3_217_000, clock_after_ms=None)


def test_empty_pgn_returns_empty_list():
    assert parse_move_times("", time_class="blitz", time_control_base_s=180) == []


def test_pgn_without_clk_returns_empty_list():
    """Pre-2020 daily games carry no %clk annotations; caller handles game-level only."""
    old_pgn = """[Event "Old Game"]
[TimeControl "1/86400"]

1. e4 e5 2. Nf3 Nc6 1-0
"""
    assert parse_move_times(old_pgn, time_class="daily") == []


def test_live_missing_base_treats_as_zero():
    """Defensive: if base is missing (unparseable time_control), every spent_ms is 0.

    Not ideal but doesn't crash. The parser is best-effort; the caller decides
    whether to suppress writes for these rows.
    """
    pgn = """[Event "?"]
[TimeControl "?"]

1. e4 {[%clk 0:03:00]} 1-0
"""
    # base_s defaults to None -> 0; current clk 180_000 -> spent (0+0)-180_000 = -180_000 -> clamped 0
    result = parse_move_times(pgn, time_class="blitz")
    assert result[0].time_spent_ms == 0
    assert result[0].clock_after_ms == 180_000
```

- [ ] **Step 2: Run tests to verify daily tests pass.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_clock_parser --keepdb
```

Expected: 7 passed (3 from prior task + 4 new).

- [ ] **Step 3: Bandit + ruff.**

```bash
ruff check services/app/games/clock_parser.py services/app/games/tests/test_clock_parser.py
bandit -ll services/app/games/clock_parser.py
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/games/tests/test_clock_parser.py && git commit -m "test(games): cover daily + edge cases in clock_parser (issue #24)

Adds tests for:
- Daily API %clk values × 10 == real inter-move delay in seconds
- Empty PGN returns []
- Pre-2020 daily PGNs without %clk return []
- Missing time_control base falls back to 0 (defensive, no crash)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Add Django Game columns + GameMoveTime model + migration

**Files:**
- Modify: `services/app/games/models.py`
- Create: `services/app/games/migrations/0004_game_time_fields_and_move_times.py`
- Create: `services/app/games/tests/test_models.py`

- [ ] **Step 1: Write the failing model test.**

Create `services/app/games/tests/test_models.py`:

```python
"""
Title: test_models.py — Tests for Game time-fields and GameMoveTime model.
Description:
    Confirms the new Game columns persist and that GameMoveTime cascades on
    Game deletion + enforces the (game, ply) unique constraint.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from datetime import datetime, timezone

from django.db import IntegrityError
from django.test import TestCase

from games.models import Game, GameMoveTime


class GameTimeFieldsTests(TestCase):
    def test_game_persists_time_columns(self):
        g = Game.objects.create(
            id="g-1",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            time_control="180+0",
            started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_class="blitz",
            time_control_base_s=180,
            time_control_increment_s=0,
        )
        g.refresh_from_db()
        assert g.started_at_utc.year == 2026
        assert g.time_class == "blitz"
        assert g.time_control_base_s == 180
        assert g.time_control_increment_s == 0


class GameMoveTimeTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(
            id="g-2",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            time_control="600+5",
            started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            time_class="rapid",
            time_control_base_s=600,
            time_control_increment_s=5,
        )

    def test_bulk_create_and_fetch(self):
        GameMoveTime.objects.bulk_create([
            GameMoveTime(game=self.game, ply=1, time_spent_ms=2_000, clock_after_ms=603_000),
            GameMoveTime(game=self.game, ply=2, time_spent_ms=5_000, clock_after_ms=600_000),
        ])
        rows = list(self.game.move_times.order_by("ply"))
        assert len(rows) == 2
        assert rows[0].time_spent_ms == 2_000
        assert rows[1].clock_after_ms == 600_000

    def test_unique_constraint_per_ply(self):
        GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=100, clock_after_ms=None)
        with self.assertRaises(IntegrityError):
            GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=200, clock_after_ms=None)

    def test_cascade_on_game_delete(self):
        GameMoveTime.objects.create(game=self.game, ply=1, time_spent_ms=100, clock_after_ms=None)
        self.game.delete()
        assert GameMoveTime.objects.count() == 0
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_models --keepdb
```

Expected: failures — column / model doesn't exist.

- [ ] **Step 3: Add new columns and model to `services/app/games/models.py`.**

Replace the contents of `services/app/games/models.py` with:

```python
"""
Title: models.py — Database models for chess games and participants
Description:
    Defines Game, GameParticipant, and GameMoveTime models. GameMoveTime
    persists per-move clock data parsed from chess.com PGNs at ingest
    time (issue #24).

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-10: Add created_at field for post-sync auto-enqueue (Task D1).
    2026-05-11: Add Game.started_at_utc / time_class / time_control_base_s
                / time_control_increment_s columns. Add GameMoveTime model.
"""

from django.db import models


class Game(models.Model):
    """A chess game record with metadata from Chess.com, PGN, and analysis."""
    id = models.CharField(max_length=64, primary_key=True)
    slug = models.SlugField(max_length=80, null=True, blank=True, unique=True, db_index=True)
    played_at = models.DateTimeField(db_index=True)
    time_control = models.CharField(max_length=32)
    white_username = models.CharField(max_length=120, null=True, blank=True)
    black_username = models.CharField(max_length=120, null=True, blank=True)
    white_rating = models.IntegerField(null=True, blank=True)
    black_rating = models.IntegerField(null=True, blank=True)
    result_pgn = models.CharField(max_length=16, null=True, blank=True)
    winner_username = models.CharField(max_length=120, null=True, blank=True)
    eco_code = models.CharField(max_length=8, default="")
    opening_name = models.CharField(max_length=120, default="")
    lichess_opening = models.CharField(max_length=200, null=True, blank=True)
    pgn = models.TextField(default="")
    created_at = models.DateTimeField(auto_now_add=True, null=True, db_index=True)

    started_at_utc = models.DateTimeField(null=True, blank=True, db_index=True)
    time_class = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    time_control_base_s = models.IntegerField(null=True, blank=True)
    time_control_increment_s = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "games"
        ordering = ["-played_at"]
        verbose_name = "Game"
        verbose_name_plural = "Games"

    def __str__(self):
        """Return human-readable game summary."""
        return f"{self.white_username} vs {self.black_username} ({self.played_at:%Y-%m-%d})"

    @property
    def display_result(self):
        """Return formatted result description (e.g., 'White won', 'Draw')."""
        if self.result_pgn == "1-0":
            return f"{self.white_username} won"
        if self.result_pgn == "0-1":
            return f"{self.black_username} won"
        if self.result_pgn == "1/2-1/2":
            return "Draw"
        return self.result_pgn or "Unknown"


class GameParticipant(models.Model):
    """Tracks player participation in a game with performance metrics."""

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="participants")
    player = models.ForeignKey("players.Player", on_delete=models.CASCADE, related_name="participations")
    color = models.CharField(max_length=8)
    opponent_username = models.CharField(max_length=120)
    player_rating = models.IntegerField(null=True, blank=True)
    opponent_rating = models.IntegerField(null=True, blank=True)
    result = models.CharField(max_length=32)
    quality_score = models.FloatField(null=True, blank=True)
    blunder_count = models.IntegerField(null=True, blank=True)
    mistake_count = models.IntegerField(null=True, blank=True)
    inaccuracy_count = models.IntegerField(null=True, blank=True)
    acpl = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "game_participants"
        unique_together = [("game", "player")]
        indexes = [
            models.Index(fields=["game"]),
            models.Index(fields=["player"]),
        ]
        verbose_name = "Game Participant"
        verbose_name_plural = "Game Participants"

    def __str__(self):
        """Return human-readable participation description."""
        return f"{self.player} ({self.color}) in {self.game_id}"


class GameMoveTime(models.Model):
    """Per-move clock data parsed from the chess.com PGN at ingest time.

    `time_spent_ms` is universal — the time the player took to respond on
    this move. `clock_after_ms` is live-only (NULL for daily). Per-move
    wall-clock submission is derivable as
    `Game.started_at_utc + cumsum(time_spent_ms[1..ply])`.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name="move_times")
    ply = models.IntegerField()
    time_spent_ms = models.IntegerField()
    clock_after_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "game_move_times"
        unique_together = [("game", "ply")]
        indexes = [
            models.Index(fields=["game", "ply"]),
        ]
        verbose_name = "Game Move Time"
        verbose_name_plural = "Game Move Times"

    def __str__(self):
        """Return human-readable description."""
        return f"{self.game_id} ply {self.ply}: {self.time_spent_ms}ms"
```

- [ ] **Step 4: Generate the migration.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py makemigrations games --name game_time_fields_and_move_times
```

Expected output: `Migrations for 'games': games/migrations/0004_game_time_fields_and_move_times.py`.

- [ ] **Step 5: Inspect the generated migration.**

Open `services/app/games/migrations/0004_game_time_fields_and_move_times.py` and verify:
- AddField operations for `started_at_utc`, `time_class`, `time_control_base_s`, `time_control_increment_s`.
- CreateModel for `GameMoveTime` with the unique constraint and index.

If anything is off (e.g., wrong field options), re-run makemigrations after fixing the model.

- [ ] **Step 6: Apply migration to the test database.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py migrate games --database=default
```

Expected: applies `0004_game_time_fields_and_move_times` cleanly.

- [ ] **Step 7: Run model tests to verify they pass.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_models
```

(Drop `--keepdb` once to let Django recreate the test DB with the new migration; re-add `--keepdb` on subsequent runs.)

Expected: 4 passed.

- [ ] **Step 8: Bandit + ruff.**

```bash
ruff check services/app/games/models.py services/app/games/tests/test_models.py services/app/games/migrations/0004_game_time_fields_and_move_times.py
bandit -ll services/app/games/models.py
```

Expected: clean.

- [ ] **Step 9: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/games/models.py services/app/games/migrations/0004_game_time_fields_and_move_times.py services/app/games/tests/test_models.py && git commit -m "feat(games): add Game time fields + GameMoveTime model (issue #24)

Adds four nullable Game columns (started_at_utc, time_class,
time_control_base_s, time_control_increment_s) and a new GameMoveTime
table keyed on (game, ply) with CASCADE on game delete. Includes the
0004 migration and model tests covering persistence, the unique
constraint, and cascade behaviour.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Mirror new columns on the SQLAlchemy Game class

**Files:**
- Modify: `services/app/app/storage/models.py`

- [ ] **Step 1: Add four columns to the SQLAlchemy Game class.**

In `services/app/app/storage/models.py`, locate the `class Game(Base):` block. After the `pgn` mapped_column line (~line 79), add:

```python
    started_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    time_class: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    time_control_base_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    time_control_increment_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

Update the file header changelog to include `2026-05-11: Add time metadata columns to Game (issue #24).`

- [ ] **Step 2: Verify the SQLAlchemy class still imports cleanly.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python -c "from app.storage.models import Game; print(Game.__table__.columns.keys())"
```

Expected: prints the column list including `started_at_utc`, `time_class`, `time_control_base_s`, `time_control_increment_s`.

- [ ] **Step 3: Bandit + ruff.**

```bash
ruff check services/app/app/storage/models.py
bandit -ll services/app/app/storage/models.py
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/app/storage/models.py && git commit -m "feat(storage): mirror new Game time columns on SQLAlchemy class (issue #24)

The legacy SQLAlchemy ingest writes to the games table directly. Mirror
the four new columns (started_at_utc, time_class, time_control_base_s,
time_control_increment_s) on the SQLAlchemy Game class so
sync_service._upsert_game can set them. No relationships, no
GameMoveTime mirror — that table is written exclusively via Django.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Populate Game time fields in the SQLAlchemy ingest

**Files:**
- Modify: `services/app/app/ingest/sync_service.py`

- [ ] **Step 1: Add the parser import and four new field assignments.**

Open `services/app/app/ingest/sync_service.py`. Find the import block near line 12-26 and add this line after the `from app.ingest.chesscom_client import ChessComClient` line:

```python
from games.time_control_parser import parse_time_control
```

In `_upsert_game` (around line 109-174), locate the section that assigns `game.played_at`, `game.time_control`, etc. (~lines 141-157). Immediately after the `game.time_control = payload.get("time_control", "")` line, insert:

```python
        # Time metadata for per-move analyses (issue #24).
        start_ts = payload.get("start_time")
        if start_ts is not None:
            game.started_at_utc = datetime.fromtimestamp(int(start_ts), tz=UTC)
        else:
            # Daily archives only — fall back to end_time so the column isn't NULL.
            game.started_at_utc = played_at
        game.time_class = payload.get("time_class") or None
        base_s, inc_s = parse_time_control(game.time_control)
        game.time_control_base_s = base_s
        game.time_control_increment_s = inc_s
```

- [ ] **Step 2: Verify the change compiles.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python -c "from app.ingest.sync_service import ChessComSyncService"
```

Expected: no error.

- [ ] **Step 3: Bandit + ruff.**

```bash
ruff check services/app/app/ingest/sync_service.py
bandit -ll services/app/app/ingest/sync_service.py
```

Expected: clean.

- [ ] **Step 4: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/app/ingest/sync_service.py && git commit -m "feat(ingest): populate Game time metadata during sync (issue #24)

sync_service._upsert_game now sets started_at_utc (from JSON
start_time, falling back to played_at when absent), time_class
(direct from JSON), and time_control_base_s / time_control_increment_s
(via games.time_control_parser.parse_time_control).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: sync_games command writes GameMoveTime rows post-sync

**Files:**
- Modify: `services/app/ingest/management/commands/sync_games.py`
- Modify: `services/app/ingest/tests/test_sync_games_command.py`

- [ ] **Step 1: Look at current shape of sync_games.py to confirm extension point.**

```bash
sed -n '1,30p' services/app/ingest/management/commands/sync_games.py
```

Identify where the subprocess call completes successfully — the GameMoveTime population happens *after* that, before the advisory lock is released.

- [ ] **Step 2: Write the failing integration test.**

In `services/app/ingest/tests/test_sync_games_command.py`, find the existing `test_*` that mocks `subprocess.run` and add a new test after it:

```python
    def test_sync_games_writes_move_times_for_synced_games(self):
        """sync_games should bulk-create GameMoveTime rows for games with %clk PGNs."""
        from games.models import Game, GameMoveTime

        # Pre-seed a game as if sync_service had just written it.
        from datetime import datetime, timezone
        Game.objects.create(
            id="test-move-times-1",
            played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            time_control="180",
            time_class="blitz",
            time_control_base_s=180,
            time_control_increment_s=0,
            started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            pgn=(
                '[Event "Live Chess"]\n[TimeControl "180"]\n\n'
                '1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:02:58]} 1-0\n'
            ),
        )

        with mock.patch(
            "ingest.management.commands.sync_games.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="ok"),
        ):
            call_command("sync_games", "alice-mt", stdout=StringIO())

        rows = list(GameMoveTime.objects.filter(game_id="test-move-times-1").order_by("ply"))
        assert len(rows) == 2
        assert rows[0].time_spent_ms == 0
        assert rows[1].time_spent_ms == 2_000
```

(Add `from unittest import mock` and `from io import StringIO` to the imports if not present.)

- [ ] **Step 3: Run the test to verify it fails.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test ingest.tests.test_sync_games_command.SyncGamesCommandTests.test_sync_games_writes_move_times_for_synced_games --keepdb
```

Expected: 0 rows (FAIL) — the post-step doesn't exist yet.

- [ ] **Step 4: Implement the post-step in sync_games.py.**

In `services/app/ingest/management/commands/sync_games.py`, add this import near the existing `from games.models import Game`:

```python
from games.clock_parser import parse_move_times
from games.models import GameMoveTime
```

After the subprocess call returns successfully and before the lock is released, add a helper function (module level) and a call inside `handle`:

```python
def _populate_move_times_for_recent_games(*, since, stdout) -> int:
    """Parse %clk annotations for any Game with non-empty PGN updated since `since`.

    Returns the number of GameMoveTime rows written. Idempotent: existing
    rows for each game are deleted and rewritten so re-ingest of a game
    leaves the table consistent.
    """
    from django.db import transaction

    written = 0
    candidates = Game.objects.filter(
        pgn__gt="",
        time_class__isnull=False,
    )
    if since is not None:
        candidates = candidates.filter(created_at__gte=since)

    for game in candidates.iterator():
        try:
            move_times = parse_move_times(
                game.pgn,
                time_class=game.time_class,
                time_control_base_s=game.time_control_base_s,
                time_control_increment_s=game.time_control_increment_s,
            )
        except Exception as exc:  # noqa: BLE001 — clock parsing is best-effort
            stdout.write(f"move-time parse failed for {game.id}: {exc}\n")
            continue
        if not move_times:
            continue
        with transaction.atomic():
            GameMoveTime.objects.filter(game=game).delete()
            GameMoveTime.objects.bulk_create([
                GameMoveTime(
                    game=game,
                    ply=mt.ply,
                    time_spent_ms=mt.time_spent_ms,
                    clock_after_ms=mt.clock_after_ms,
                )
                for mt in move_times
            ])
            written += len(move_times)
    return written
```

Then inside `handle`, after the subprocess succeeds (look for the existing `enqueue_unanalyzed` / `subprocess.run` block — the call should go right after the subprocess returns):

```python
        # Issue #24: populate per-move clock data for games written by the
        # subprocess. We pass `since=None` for now (full sweep is cheap and
        # idempotent); the backfill command handles bulk historic loads.
        try:
            written = _populate_move_times_for_recent_games(since=None, stdout=self.stdout)
            self.stdout.write(f"move-time rows written: {written}\n")
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(f"move-time post-step failed: {exc}\n")
```

(If a `since` variable is already in scope reflecting the sync start time, pass that instead of `None`. Otherwise leave as `None` — see implementation note below the test plan.)

- [ ] **Step 5: Run the integration test to verify it passes.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test ingest.tests.test_sync_games_command --keepdb
```

Expected: all tests in this module pass, including the new one.

- [ ] **Step 6: Bandit + ruff.**

```bash
ruff check services/app/ingest/management/commands/sync_games.py services/app/ingest/tests/test_sync_games_command.py
bandit -ll services/app/ingest/management/commands/sync_games.py
```

Expected: clean.

- [ ] **Step 7: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/ingest/management/commands/sync_games.py services/app/ingest/tests/test_sync_games_command.py && git commit -m "feat(ingest): sync_games populates GameMoveTime rows post-sync (issue #24)

After the SQLAlchemy ingest subprocess completes, the Django sync_games
command walks every Game with non-empty PGN and a known time_class,
parses the PGN via games.clock_parser.parse_move_times, and bulk-creates
GameMoveTime rows. Failure to parse one game logs and skips; the rest of
the sweep continues. Re-ingest of an existing game deletes and rewrites
its move_times rows for idempotency.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: One-shot backfill management command

**Files:**
- Create: `services/app/games/management/__init__.py`
- Create: `services/app/games/management/commands/__init__.py`
- Create: `services/app/games/management/commands/backfill_move_times.py`
- Create: `services/app/games/tests/test_backfill_move_times.py`

- [ ] **Step 1: Verify management dirs exist.**

```bash
ls services/app/games/management/ 2>/dev/null || mkdir -p services/app/games/management/commands
test -f services/app/games/management/__init__.py || touch services/app/games/management/__init__.py
test -f services/app/games/management/commands/__init__.py || touch services/app/games/management/commands/__init__.py
```

- [ ] **Step 2: Write the failing test.**

Create `services/app/games/tests/test_backfill_move_times.py`:

```python
"""
Title: test_backfill_move_times.py — Tests for the backfill management command.
Description:
    Verifies the command writes GameMoveTime rows for games with valid PGN,
    is idempotent on re-run, honours --limit, and reports counts in --dry-run.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from datetime import datetime, timezone
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from games.models import Game, GameMoveTime


_PGN_LIVE = (
    '[Event "Live Chess"]\n[TimeControl "180"]\n\n'
    '1. e4 {[%clk 0:03:00]} 1... c5 {[%clk 0:02:58]} 1-0\n'
)
_PGN_DAILY = (
    '[Event "Lets Play!"]\n[TimeControl "1/604800"]\n\n'
    '1. e4 {[%clk 0:00:00.5]} 1... c6 {[%clk 0:30:05.2]} 1-0\n'
)


def _make_game(game_id, *, time_class, time_control, base_s, inc_s, pgn):
    return Game.objects.create(
        id=game_id,
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control=time_control,
        time_class=time_class,
        time_control_base_s=base_s,
        time_control_increment_s=inc_s,
        started_at_utc=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        pgn=pgn,
    )


class BackfillMoveTimesTests(TestCase):
    def test_writes_rows_for_live_and_daily(self):
        _make_game("bf-1", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        _make_game("bf-2", time_class="daily", time_control="1/604800", base_s=604800, inc_s=None, pgn=_PGN_DAILY)

        out = StringIO()
        call_command("backfill_move_times", stdout=out)

        assert GameMoveTime.objects.filter(game_id="bf-1").count() == 2
        assert GameMoveTime.objects.filter(game_id="bf-2").count() == 2

    def test_idempotent_on_rerun(self):
        _make_game("bf-3", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        call_command("backfill_move_times", stdout=StringIO())
        call_command("backfill_move_times", stdout=StringIO())  # no double-write
        assert GameMoveTime.objects.filter(game_id="bf-3").count() == 2

    def test_dry_run_writes_nothing(self):
        _make_game("bf-4", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        out = StringIO()
        call_command("backfill_move_times", "--dry-run", stdout=out)
        assert GameMoveTime.objects.filter(game_id="bf-4").count() == 0
        assert "would write" in out.getvalue().lower()

    def test_limit_caps_processing(self):
        _make_game("bf-5", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        _make_game("bf-6", time_class="blitz", time_control="180", base_s=180, inc_s=0, pgn=_PGN_LIVE)
        call_command("backfill_move_times", "--limit", "1", stdout=StringIO())
        total = GameMoveTime.objects.filter(game_id__in=["bf-5", "bf-6"]).count()
        assert total == 2  # exactly one game processed (2 plies each)
```

- [ ] **Step 3: Run tests to verify they fail.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_backfill_move_times --keepdb
```

Expected: ImportError or "no such command".

- [ ] **Step 4: Implement the command.**

Create `services/app/games/management/commands/backfill_move_times.py`:

```python
"""
Title: backfill_move_times.py — One-shot backfill of GameMoveTime rows
Description:
    Sweeps every Game with non-empty pgn and a known time_class, parses
    the %clk annotations via games.clock_parser.parse_move_times, and
    bulk-creates GameMoveTime rows. Idempotent: rewrites existing rows
    per game inside a transaction. Pre-2020 daily games (no %clk) are
    skipped silently.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from games.clock_parser import parse_move_times
from games.models import Game, GameMoveTime


_BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Backfill GameMoveTime rows from existing Game.pgn data."

    def add_arguments(self, parser):
        """Register CLI flags for the command."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse + report counts without writing.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of games to process (useful for smoke testing).",
        )

    def handle(self, *args, **options):
        """Iterate Games, parse PGN, bulk-write GameMoveTime rows."""
        dry_run: bool = options["dry_run"]
        limit: int | None = options["limit"]

        qs = Game.objects.filter(pgn__gt="", time_class__isnull=False).order_by("id")
        if limit is not None:
            qs = qs[:limit]

        games_seen = 0
        rows_written = 0
        rows_planned = 0
        failures = 0

        for game in qs.iterator(chunk_size=_BATCH_SIZE):
            games_seen += 1
            try:
                move_times = parse_move_times(
                    game.pgn,
                    time_class=game.time_class,
                    time_control_base_s=game.time_control_base_s,
                    time_control_increment_s=game.time_control_increment_s,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort parse
                failures += 1
                self.stdout.write(
                    self.style.WARNING(f"  parse failed for {game.id}: {exc}")
                )
                continue
            if not move_times:
                continue
            if dry_run:
                rows_planned += len(move_times)
                continue
            with transaction.atomic():
                GameMoveTime.objects.filter(game=game).delete()
                GameMoveTime.objects.bulk_create([
                    GameMoveTime(
                        game=game,
                        ply=mt.ply,
                        time_spent_ms=mt.time_spent_ms,
                        clock_after_ms=mt.clock_after_ms,
                    )
                    for mt in move_times
                ])
                rows_written += len(move_times)

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN: scanned {games_seen} games, would write {rows_planned} rows, "
                    f"{failures} parse failures."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backfill complete: scanned {games_seen} games, wrote {rows_written} rows, "
                    f"{failures} parse failures."
                )
            )
```

- [ ] **Step 5: Run tests to verify they pass.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test games.tests.test_backfill_move_times --keepdb
```

Expected: 4 passed.

- [ ] **Step 6: Bandit + ruff.**

```bash
ruff check services/app/games/management/commands/backfill_move_times.py services/app/games/tests/test_backfill_move_times.py
bandit -ll services/app/games/management/commands/backfill_move_times.py
```

Expected: clean.

- [ ] **Step 7: Commit.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git add services/app/games/management/__init__.py services/app/games/management/commands/__init__.py services/app/games/management/commands/backfill_move_times.py services/app/games/tests/test_backfill_move_times.py && git commit -m "feat(games): backfill_move_times management command (issue #24)

One-shot Django command that scans every Game with non-empty pgn and a
known time_class, parses the %clk annotations, and bulk-writes
GameMoveTime rows. Idempotent (rewrites per game in a transaction).
Supports --dry-run for safe inspection and --limit for smoke tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Full app test suite + linting sweep

**Files:** None (verification only).

- [ ] **Step 1: Run the full app test suite.**

```bash
cd services/app && SECRET_KEY=test-secret DEBUG=true DATABASE_URL=postgres://christopherwebster@localhost:5432/wood_league /Users/christopherwebster/Projects/wood_league/.venv/bin/python manage.py test api.tests games.tests ingest.tests --keepdb
```

Expected: all green. If any pre-existing test fails because of the schema change (e.g., a test creates a Game without supplying the new columns and a downstream assertion barfs), inspect, fix or note. The new columns are all nullable so default construction should still succeed.

- [ ] **Step 2: Run ruff across the whole touched surface.**

```bash
ruff check services/app/games/ services/app/app/storage/models.py services/app/app/ingest/sync_service.py services/app/ingest/management/commands/sync_games.py services/app/ingest/tests/test_sync_games_command.py
```

Expected: All checks passed.

- [ ] **Step 3: Run bandit across the whole touched surface.**

```bash
bandit -ll services/app/games/clock_parser.py services/app/games/time_control_parser.py services/app/games/models.py services/app/games/management/commands/backfill_move_times.py services/app/app/storage/models.py services/app/app/ingest/sync_service.py services/app/ingest/management/commands/sync_games.py
```

Expected: no medium/high findings.

- [ ] **Step 4: No commit needed — verification only.**

---

### Task 10: Open PR

**Files:** None (workflow).

- [ ] **Step 1: Push branch.**

```bash
cd /Users/christopherwebster/Projects/wood_league && git push -u origin issue/24-move-timing-ingest-spec
```

- [ ] **Step 2: Open PR via gh.**

```bash
gh pr create --title "feat(games): move-timing ingest from chess.com PGN" --body "$(cat <<'EOF'
Closes #24.

## Summary
Persist per-move clock data parsed from chess.com PGNs into a new \`GameMoveTime\` table at ingest time, plus four time-related columns on \`Game\`. Enables time-of-day, time-pressure, and quality-vs-think-time analyses across the existing corpus and going forward.

## What ships
- Two pure-Python parser modules: \`games.clock_parser\` (live deltas + daily decisecond scaling) and \`games.time_control_parser\` (live/daily TC strings).
- New Django model \`GameMoveTime(game, ply, time_spent_ms, clock_after_ms)\` with \`unique_together(game, ply)\` and CASCADE on game delete. Migration \`0004\`.
- Four nullable Game columns: \`started_at_utc\`, \`time_class\`, \`time_control_base_s\`, \`time_control_increment_s\`.
- SQLAlchemy \`Game\` mirror class updated so the legacy ingest can write the new columns.
- \`sync_service._upsert_game\` populates the new Game columns during normal ingest.
- \`sync_games\` Django command post-step bulk-writes \`GameMoveTime\` rows for newly-synced games (failures isolated per game).
- One-shot \`manage.py backfill_move_times\` for the existing corpus (\`--dry-run\` and \`--limit\` supported).

## Test plan
- [x] \`manage.py test api.tests games.tests ingest.tests\` — full green
- [x] ruff + bandit clean on all touched files
- [ ] After merge: run \`manage.py backfill_move_times --dry-run\` on Railway shell to estimate row counts
- [ ] After merge: run \`manage.py backfill_move_times\` to populate historical rows

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Done.** Stop here. Merging, tagging, and backfill are user-driven decisions handled outside the plan.

---

## Implementation note on `since=` in Task 7

The sync_games command already mutates the database via subprocess. There's no clean per-game "newly inserted" signal exposed from the subprocess back to the parent Django command. Two options for the post-step:

1. **Full sweep** (chosen above): walk every Game with non-empty PGN. Idempotent — re-writing existing rows is cheap (single transaction per game, < 1ms each). Simplest and safest.
2. **`since=now()` filter**: only process Games whose `created_at >= sync_start_time`. Faster on subsequent syncs but requires capturing the timestamp before the subprocess call.

The implementation uses option 1 (`since=None`). If the cron sweep becomes slow once the corpus grows past ~100k games, switch to option 2 by recording `sync_start = timezone.now()` before the subprocess and passing it through. Until then, simpler wins.

---

## Self-review

**Spec coverage check (against `docs/superpowers/specs/2026-05-11-move-timing-ingest-design.md`):**

| Spec section | Covered by |
|---|---|
| Game schema (4 new columns) | Task 4 |
| `GameMoveTime` schema | Task 4 |
| Parser (`clock_parser.py`) | Tasks 2, 3 |
| Time-control parser | Task 1 |
| SQLAlchemy mirror update | Task 5 |
| Ingest integration (sync_service) | Task 6 |
| Ingest integration (sync_games post-step) | Task 7 |
| Backfill management command | Task 8 |
| Unit tests (live + daily + edge) | Tasks 1, 2, 3 |
| Integration tests (post-sync) | Task 7 |
| Integration tests (backfill) | Task 8 |
| Negative-delta clamping | Task 2 |
| `time_spent` formula with increment | Task 2 |
| Idempotency of writes | Tasks 7, 8 |
| Failure isolation | Tasks 7, 8 |

No spec sections without a corresponding task. Verification queries from the spec (sum-of-spent-ms ≤ wall-clock) are out of scope here — covered by ad-hoc post-backfill inspection rather than a formal test.

**Placeholder scan:** No "TBD", "TODO", "fill in details", or unspecified error-handling steps. All code blocks are complete.

**Type consistency:** `MoveTime` fields (`ply`, `time_spent_ms`, `clock_after_ms`) are consistent across the parser definition (Task 2), tests (Tasks 2/3), the post-step (Task 7), and the backfill (Task 8). The `parse_move_times` signature is identical in every place it's called. The `GameMoveTime` model field names match what the parser produces.

**Ambiguity check:** All references to file paths, command names, and field names are explicit. The one judgement call — option 1 vs option 2 for the sync-games post-step `since=` parameter — is documented under "Implementation note" so reviewers can override if they want.
