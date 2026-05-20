# Search Page Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `/search/` per issue #162 — humanised copy + AI prompt, new game-table columns, modal preview with opening link and accuracy chips, opening_id ingested on Game.

**Architecture:** Add `Game.opening` FK denormalised at ingest. Add pure formatter helpers (`format_time_control`, `opening_notation`, `accuracy_band_class`) and a `resolve_current_player` lookup. Build a reusable Tailwind+HTMX `wc-modal` component via the frontend-design skill. Wire the AI prompt to teach it self-reference, club vocabulary, and the players directory. Replace the side-panel preview with a row-click modal partial.

**Tech Stack:** Django 5 · Tailwind · HTMX · python-chess · Anthropic API · pytest

**Spec:** `docs/superpowers/specs/2026-05-20-search-page-rework-design.md`

**Branch:** `issue/162-search-page-rework`

---

## Setup (already done)

- Branch `issue/162-search-page-rework` exists with the spec committed.
- Working dir: `/Users/christopherwebster/Projects/wood_league`
- Activate venv before any pytest/bandit/python invocation:
  ```bash
  source .venv/bin/activate
  ```
- App working dir for Django commands: `services/app/`

---

## Task 1: `format_time_control` helper

**Files:**
- Create: `services/app/games/time_control_format.py`
- Test: `services/app/games/tests/test_time_control_format.py`

- [ ] **Step 1: Write failing tests**

Create `services/app/games/tests/test_time_control_format.py`:

```python
"""
Title: test_time_control_format.py
Description: Tests for the human-readable time-control formatter.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from games.time_control_format import format_time_control


@pytest.mark.parametrize("base,inc,expected", [
    (86400, 0, "1 day per move"),
    (172800, 0, "2 days per move"),
    (259200, None, "3 days per move"),
    (900, 10, "15+10 min"),
    (600, 5, "10+5 min"),
    (180, 0, "3 min"),
    (60, 0, "1 min"),
    (30, 0, "30+0 sec"),
    (30, 2, "30+2 sec"),
])
def test_format_time_control_known_shapes(base, inc, expected):
    assert format_time_control(base, inc) == expected


def test_format_time_control_falls_back_to_raw():
    assert format_time_control(None, None, raw="weird/123") == "weird/123"


def test_format_time_control_none_no_raw_returns_empty():
    assert format_time_control(None, None) == ""
```

- [ ] **Step 2: Run tests, expect FAIL (import error)**

```bash
source .venv/bin/activate && cd services/app && \
  pytest games/tests/test_time_control_format.py -q
```
Expected: collection error / import failure.

- [ ] **Step 3: Implement**

Create `services/app/games/time_control_format.py`:

```python
"""
Title: time_control_format.py — Human-readable time-control formatter
Description:
    Pure helper that turns parsed (base_seconds, increment_seconds) values
    into a short human label used by the search results table and game
    preview modal. Falls back to a caller-supplied raw string when the
    values are unknown.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations


def format_time_control(
    base_seconds: int | None,
    increment_seconds: int | None,
    *,
    raw: str | None = None,
) -> str:
    """Render a time control as a short human-readable label.

    Args:
        base_seconds: Per-game base time (or per-move budget for daily).
        increment_seconds: Increment in seconds; ``None`` for daily formats.
        raw: Optional original chess.com string used as a fallback when
            neither field parsed.

    Returns:
        ``"1 day per move"``, ``"15+10 min"``, ``"3 min"``, ``"30+2 sec"``,
        the raw string if provided, or ``""`` when nothing is parseable.
    """
    if base_seconds is None and increment_seconds is None:
        return raw or ""

    if increment_seconds is None and base_seconds is not None and base_seconds >= 86400:
        days = base_seconds // 86400
        return f"{days} day per move" if days == 1 else f"{days} days per move"

    if base_seconds is None:
        return raw or ""

    if base_seconds >= 60 and (increment_seconds or 0) == 0:
        minutes = base_seconds // 60
        return f"{minutes} min"
    if base_seconds >= 60:
        minutes = base_seconds // 60
        return f"{minutes}+{increment_seconds} min"
    return f"{base_seconds}+{increment_seconds or 0} sec"
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest games/tests/test_time_control_format.py -q
```

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll games/time_control_format.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/time_control_format.py services/app/games/tests/test_time_control_format.py
git commit -m "feat(#162): format_time_control human-readable helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `opening_notation` helper

**Files:**
- Create: `services/app/games/opening_notation.py`
- Test: `services/app/games/tests/test_opening_notation.py`

- [ ] **Step 1: Write failing tests**

Create `services/app/games/tests/test_opening_notation.py`:

```python
"""
Title: test_opening_notation.py
Description: Tests for truncated PGN move-list rendering.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from games.opening_notation import opening_notation


PGN_5PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *"""
PGN_10PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 *"""
PGN_30PLY = """[Event "test"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O 9. h3 Nb8 10. d4 Nbd7 11. Nbd2 Bb7 12. Bc2 Re8 13. Nf1 Bf8 14. Ng3 g6 15. a4 c5 *"""


def test_opening_notation_empty():
    assert opening_notation("") == ""


def test_opening_notation_short_returns_all():
    assert opening_notation(PGN_5PLY) == "1. e4 e5 2. Nf3 Nc6 3. Bb5"


def test_opening_notation_exactly_max_no_ellipsis():
    assert opening_notation(PGN_10PLY, max_plies=10) == \
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7"


def test_opening_notation_truncates_with_ellipsis():
    out = opening_notation(PGN_30PLY, max_plies=10)
    assert out.endswith("…")
    assert out.startswith("1. e4 e5 2. Nf3 Nc6")
    assert " 6." not in out


def test_opening_notation_handles_malformed_pgn():
    assert opening_notation("not a pgn at all") == ""
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
pytest games/tests/test_opening_notation.py -q
```

- [ ] **Step 3: Implement**

Create `services/app/games/opening_notation.py`:

```python
"""
Title: opening_notation.py — Truncated PGN move list
Description:
    Returns a short SAN move list (``"1. e4 e5 2. Nf3 Nc6 …"``) suitable for
    a search-results cell. Truncates to ``max_plies`` half-moves and
    appends an ellipsis when the game has more.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

import io

import chess.pgn


def opening_notation(pgn_text: str, max_plies: int = 10) -> str:
    """Render the first ``max_plies`` plies of ``pgn_text`` as SAN notation.

    Args:
        pgn_text: Raw PGN string (may be empty).
        max_plies: Maximum half-moves to include; default 10 (move 5 both
            sides).

    Returns:
        A string such as ``"1. e4 e5 2. Nf3 Nc6 3. Bb5"``. Appends
        ``"…"`` if the source has more plies than ``max_plies``. Returns
        ``""`` for empty or unparseable input.
    """
    if not pgn_text or not pgn_text.strip():
        return ""
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive: chess.pgn raises a variety
        return ""
    if game is None:
        return ""

    board = game.board()
    parts: list[str] = []
    total = 0
    truncated = False
    for ply_index, move in enumerate(game.mainline_moves()):
        if ply_index >= max_plies:
            truncated = True
            break
        san = board.san(move)
        if ply_index % 2 == 0:
            move_no = (ply_index // 2) + 1
            parts.append(f"{move_no}. {san}")
        else:
            parts.append(san)
        board.push(move)
        total += 1

    # Count remaining plies to decide ellipsis if the loop exhausted early.
    if not truncated:
        remaining = sum(1 for _ in game.mainline_moves()) - total
        truncated = remaining > 0 and total >= max_plies

    text = " ".join(parts)
    return f"{text} …" if truncated else text
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest games/tests/test_opening_notation.py -q
```

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll games/opening_notation.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/opening_notation.py services/app/games/tests/test_opening_notation.py
git commit -m "feat(#162): opening_notation truncated PGN helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `resolve_opening_id` PGN → OpeningBook walker

**Files:**
- Create: `services/app/games/opening_resolver.py`
- Test: `services/app/games/tests/test_opening_resolver.py`

- [ ] **Step 1: Write failing tests**

Create `services/app/games/tests/test_opening_resolver.py`:

```python
"""
Title: test_opening_resolver.py
Description: Tests resolve_opening_id walks the PGN through the OpeningBook
    and returns the deepest matching opening id.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from games.opening_resolver import resolve_opening_id


@pytest.fixture
def patched_lookup(monkeypatch):
    """Patch openings.services.lookup_opening_entry to a scripted sequence.

    Each call corresponds to one board position; returning None on the
    deeper boards mirrors a real walk that exits the book.
    """
    calls = {"n": 0}

    def factory(seq):
        def fake(_board):
            i = calls["n"]
            calls["n"] += 1
            return seq[i] if i < len(seq) else None
        monkeypatch.setattr(
            "games.opening_resolver.lookup_opening_entry", fake
        )
        return calls

    return factory


def test_resolve_returns_deepest_hit(patched_lookup):
    patched_lookup([
        (1, "B00", "King's Pawn"),       # start
        (1, "B00", "King's Pawn"),       # after 1. e4
        (7, "C40", "King's Knight"),     # after 1...e5
        None,                            # after 2. Nf3 — exits book
    ])
    pgn = """[Event "t"]\n\n1. e4 e5 2. Nf3 Nc6 *"""
    assert resolve_opening_id(pgn) == 7


def test_resolve_no_hits(patched_lookup):
    patched_lookup([None])
    assert resolve_opening_id("[Event \"t\"]\n\n1. a3 *") is None


def test_resolve_empty_pgn():
    assert resolve_opening_id("") is None


def test_resolve_malformed_pgn():
    assert resolve_opening_id("garbage not pgn") is None
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
pytest games/tests/test_opening_resolver.py -q
```

- [ ] **Step 3: Implement**

Create `services/app/games/opening_resolver.py`:

```python
"""
Title: opening_resolver.py — Resolve a PGN to its deepest OpeningBook id
Description:
    Walks a PGN ply by ply, querying ``openings.lookup_opening_entry`` for
    each position, and returns the id of the deepest board that still
    matched the book. Used at game ingest to denormalise
    ``Game.opening_id`` so downstream views can link to the opening
    detail page without re-parsing the PGN.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

import io

import chess.pgn

from openings.services import lookup_opening_entry


def resolve_opening_id(pgn_text: str) -> int | None:
    """Return the deepest OpeningBook id reachable from ``pgn_text``.

    Args:
        pgn_text: Raw PGN. Empty / unparseable input yields ``None``.

    Returns:
        Integer ``OpeningBook.id`` of the deepest matching node, or
        ``None`` when no position in the game matched.
    """
    if not pgn_text or not pgn_text.strip():
        return None
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive
        return None
    if game is None:
        return None

    board = game.board()
    deepest: int | None = None
    hit = lookup_opening_entry(board)
    if hit is not None:
        deepest = hit[0]
    for move in game.mainline_moves():
        board.push(move)
        hit = lookup_opening_entry(board)
        if hit is None:
            break
        deepest = hit[0]
    return deepest
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest games/tests/test_opening_resolver.py -q
```

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll games/opening_resolver.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/opening_resolver.py services/app/games/tests/test_opening_resolver.py
git commit -m "feat(#162): resolve_opening_id PGN→OpeningBook walker

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add `Game.opening` FK + migration

**Files:**
- Modify: `services/app/games/models.py`
- Create: `services/app/games/migrations/00NN_game_opening_fk.py` (Django auto-generates)
- Test: `services/app/games/tests/test_models.py` (append)

- [ ] **Step 1: Add failing test**

Append to `services/app/games/tests/test_models.py`:

```python
def test_game_has_opening_fk(db):
    """Game.opening is a nullable FK to openings.OpeningBook."""
    from games.models import Game
    field = Game._meta.get_field("opening")
    assert field.null is True
    assert field.related_model.__name__ == "OpeningBook"
```

- [ ] **Step 2: Run, expect FAIL**

```bash
pytest games/tests/test_models.py::test_game_has_opening_fk -q
```

- [ ] **Step 3: Edit `services/app/games/models.py`** — locate the `Game` class and add after `lichess_opening`:

```python
    opening = models.ForeignKey(
        "openings.OpeningBook",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="games",
        help_text=(
            "Resolved OpeningBook entry — denormalised at ingest by "
            "games.opening_resolver.resolve_opening_id."
        ),
    )
```

- [ ] **Step 4: Generate + run migration**

```bash
cd services/app
python manage.py makemigrations games --name game_opening_fk
python manage.py migrate games
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest games/tests/test_models.py::test_game_has_opening_fk -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/models.py services/app/games/migrations/
git commit -m "feat(#162): add Game.opening FK to OpeningBook

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire `resolve_opening_id` into the ingest path

**Files:**
- Modify: `services/app/games/services.py` (or whichever module persists Games from PGN)

- [ ] **Step 1: Find ingest call site**

```bash
cd services/app
grep -nE "Game\.objects\.(create|update_or_create|get_or_create)|Game\(.*pgn" games/ ingest/ -r
```

Identify the function that creates / updates Game rows from PGN. Likely candidates: `games/services.py`, an `ingest` app, or a chess.com importer module.

- [ ] **Step 2: Add failing integration test**

Create or extend `services/app/games/tests/test_ingest_opening.py`:

```python
"""
Title: test_ingest_opening.py
Description: Ingest writes Game.opening_id resolved from the PGN.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest
from unittest import mock

# Replace IMPORT_PATH below with the actual ingest function discovered in Step 1.
# Example placeholder using games.services.upsert_game_from_pgn — adapt as needed.
from games.services import upsert_game_from_pgn  # noqa: E402


@pytest.mark.django_db
def test_ingest_writes_opening_id():
    fake_pgn = """[Event "t"]\n[White "a"]\n[Black "b"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 *"""
    with mock.patch(
        "games.services.resolve_opening_id", return_value=42
    ):
        game = upsert_game_from_pgn(fake_pgn, source_id="test-1")
    assert game.opening_id == 42
```

(If `upsert_game_from_pgn` doesn't exist, replace with the actual ingest function name from Step 1; if the ingest is on a different module path, update the patch target accordingly.)

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest games/tests/test_ingest_opening.py -q
```

- [ ] **Step 4: Add the resolver call**

At the top of the ingest module:

```python
from games.opening_resolver import resolve_opening_id
```

In the ingest function, just before persisting:

```python
game.opening_id = resolve_opening_id(pgn_text)
```

(Adjust to the function's local variable names — `pgn_text`, `pgn`, or `game.pgn`.)

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest games/tests/test_ingest_opening.py -q
```

- [ ] **Step 6: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/
git commit -m "feat(#162): resolve opening_id on game ingest

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Backfill management command

**Files:**
- Create: `services/app/games/management/commands/backfill_opening_ids.py`
- Test: `services/app/games/tests/test_backfill_opening_ids.py`

- [ ] **Step 1: Write failing test**

Create `services/app/games/tests/test_backfill_opening_ids.py`:

```python
"""
Title: test_backfill_opening_ids.py
Description: backfill_opening_ids fills Game.opening_id for null rows.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest
from unittest import mock

from django.core.management import call_command

from games.models import Game


@pytest.mark.django_db
def test_backfill_sets_opening_id(monkeypatch):
    g = Game.objects.create(
        id="t1", slug="t-1",
        pgn="[Event \"t\"]\n\n1. e4 e5 *",
    )
    monkeypatch.setattr(
        "games.management.commands.backfill_opening_ids.resolve_opening_id",
        lambda _pgn: 99,
    )
    call_command("backfill_opening_ids")
    g.refresh_from_db()
    assert g.opening_id == 99


@pytest.mark.django_db
def test_backfill_dry_run_does_not_write(monkeypatch):
    g = Game.objects.create(id="t2", slug="t-2", pgn="x")
    monkeypatch.setattr(
        "games.management.commands.backfill_opening_ids.resolve_opening_id",
        lambda _pgn: 1,
    )
    call_command("backfill_opening_ids", "--dry-run")
    g.refresh_from_db()
    assert g.opening_id is None
```

- [ ] **Step 2: Run, expect FAIL**

```bash
pytest games/tests/test_backfill_opening_ids.py -q
```

- [ ] **Step 3: Implement command**

Create `services/app/games/management/commands/backfill_opening_ids.py`:

```python
"""
Title: backfill_opening_ids.py — Backfill Game.opening_id for legacy rows
Description:
    Iterates ``Game`` rows where ``opening_id IS NULL`` and writes the
    resolver's best match. Idempotent; safe to re-run. Used after the
    #162 migration that added the FK.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from games.models import Game
from games.opening_resolver import resolve_opening_id


class Command(BaseCommand):
    """Backfill the denormalised Game.opening_id column."""

    help = "Backfill Game.opening_id for rows where it is NULL."

    def add_arguments(self, parser):
        """Register CLI flags."""
        parser.add_argument(
            "--batch", type=int, default=500,
            help="Rows fetched per page (default 500).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Compute matches but do not write.",
        )

    def handle(self, *args, **opts):
        """Run the backfill, logging counts to stdout."""
        batch = opts["batch"]
        dry = opts["dry_run"]
        resolved = 0
        unresolved = 0
        errors = 0

        qs = Game.objects.filter(opening_id__isnull=True).only("id", "pgn")
        total = qs.count()
        self.stdout.write(f"backfill_opening_ids: {total} rows to process")

        for start in range(0, total, batch):
            chunk = list(qs[start:start + batch])
            for game in chunk:
                try:
                    oid = resolve_opening_id(game.pgn or "")
                except Exception as exc:  # noqa: BLE001 — log & skip per row
                    errors += 1
                    self.stderr.write(f"game={game.id}: {exc}")
                    continue
                if oid is None:
                    unresolved += 1
                    continue
                resolved += 1
                if not dry:
                    Game.objects.filter(pk=game.pk).update(opening_id=oid)

        self.stdout.write(
            f"done: resolved={resolved} unresolved={unresolved} "
            f"errors={errors} dry_run={dry}"
        )
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pytest games/tests/test_backfill_opening_ids.py -q
```

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll games/management/commands/backfill_opening_ids.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/management/commands/backfill_opening_ids.py \
        services/app/games/tests/test_backfill_opening_ids.py
git commit -m "feat(#162): backfill_opening_ids management command

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `resolve_current_player` lookup

**Files:**
- Create: `services/app/accounts/services.py`
- Test: `services/app/accounts/tests/test_services.py` (create dir if needed)

- [ ] **Step 1: Make tests dir if missing**

```bash
cd services/app
[ -d accounts/tests ] || mkdir accounts/tests && touch accounts/tests/__init__.py
```

If a `accounts/tests.py` file exists and shadows the directory, also create the dir then leave the file alone — pytest still discovers `tests/` if `tests.py` isn't a package; if collision, rename `tests.py` to `tests/test_legacy.py`.

- [ ] **Step 2: Write failing test**

Create `services/app/accounts/tests/test_services.py`:

```python
"""
Title: test_services.py — accounts.services unit tests
Description: Tests resolve_current_player maps a Django user to a Player.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from accounts.models import User
from accounts.services import resolve_current_player
from players.models import Player


@pytest.mark.django_db
def test_resolve_returns_player_when_email_matches():
    user = User.objects.create_user(email="chris@example.com", password="x")
    player = Player.objects.create(
        username="chris", display_name="Chris", email="chris@example.com",
    )
    assert resolve_current_player(user) == player


@pytest.mark.django_db
def test_resolve_returns_none_when_no_player():
    user = User.objects.create_user(email="ghost@example.com", password="x")
    assert resolve_current_player(user) is None


def test_resolve_returns_none_for_anonymous():
    class Anon:
        is_authenticated = False
        email = ""

    assert resolve_current_player(Anon()) is None
```

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest accounts/tests/test_services.py -q
```

- [ ] **Step 4: Implement**

Create `services/app/accounts/services.py`:

```python
"""
Title: services.py — accounts service helpers
Description:
    Bridges Django's authenticated ``User`` (email-keyed) to the
    Wood-League ``Player`` row keyed by the same email. Used by the
    search view to thread the current user's club username into the
    AI prompt so "I/me/my/mine" resolves correctly.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from players.models import Player


def resolve_current_player(user) -> Player | None:
    """Return the ``Player`` matching ``user.email`` or ``None``.

    Args:
        user: A Django request user (authenticated or anonymous).

    Returns:
        The matching ``Player`` row, or ``None`` when the user is
        anonymous, has no email, or no Player carries that email.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    email = (getattr(user, "email", "") or "").strip().lower()
    if not email:
        return None
    return Player.objects.filter(email__iexact=email).first()
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest accounts/tests/test_services.py -q
```

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll accounts/services.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/accounts/services.py services/app/accounts/tests/
git commit -m "feat(#162): resolve_current_player(user) -> Player

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Template tags — `time_control_human`, `opening_notation`, `accuracy_band_class`, `club_accuracy_chips`

**Files:**
- Create: `services/app/games/templatetags/__init__.py` (if missing)
- Create: `services/app/games/templatetags/game_format.py`
- Test: `services/app/games/tests/test_game_format_tags.py`

- [ ] **Step 1: Ensure templatetags dir exists**

```bash
cd services/app
[ -f games/templatetags/__init__.py ] || (mkdir -p games/templatetags && touch games/templatetags/__init__.py)
```

- [ ] **Step 2: Write failing tests**

Create `services/app/games/tests/test_game_format_tags.py`:

```python
"""
Title: test_game_format_tags.py — Template-tag unit tests
Description: Asserts the formatter and band-class tags emit the right
    strings without rendering a full template.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest
from unittest import mock

from games.templatetags.game_format import (
    accuracy_band_class,
    club_accuracy_chips,
    opening_notation_filter,
    time_control_human,
)


class FakeGame:
    """Stand-in for a Game model with the attributes the tags read."""

    def __init__(self, **kw):
        self.time_control_base_s = kw.get("base")
        self.time_control_increment_s = kw.get("inc")
        self.time_control = kw.get("raw", "")
        self.pgn = kw.get("pgn", "")


def test_time_control_human():
    g = FakeGame(base=900, inc=10)
    assert time_control_human(g) == "15+10 min"


def test_opening_notation_filter_default_max_10():
    pgn = "[Event \"t\"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 *"
    assert opening_notation_filter(pgn) == "1. e4 e5 2. Nf3 Nc6 3. Bb5"


@pytest.mark.parametrize("acc,expected", [
    (95, "wc-chip wc-chip--band-strong"),
    (85, "wc-chip wc-chip--band-good"),
    (75, "wc-chip wc-chip--band-fair"),
    (65, "wc-chip wc-chip--band-weak"),
    (40, "wc-chip wc-chip--band-poor"),
    (None, "wc-chip wc-chip--band-unknown"),
])
def test_accuracy_band_class(acc, expected):
    assert accuracy_band_class(acc) == expected


def test_club_accuracy_chips_only_club_members():
    """Only sides whose username is in the club directory get a chip."""
    chips = club_accuracy_chips(
        white_username="chris", black_username="strangerbot",
        club_usernames={"chris": "Chris"},
        sf_white=87, sf_black=70, lc0_white=78, lc0_black=None,
    )
    assert len(chips) == 1
    assert chips[0]["display_name"] == "Chris"
    assert chips[0]["sf"] == 87
    assert chips[0]["lc0"] == 78
    assert "wc-chip--band-good" in chips[0]["band_class"]


def test_club_accuracy_chips_omits_missing_engine():
    chips = club_accuracy_chips(
        white_username="chris", black_username="alice",
        club_usernames={"chris": "Chris", "alice": "Alice"},
        sf_white=87, sf_black=None, lc0_white=None, lc0_black=80,
    )
    assert len(chips) == 2
    chris, alice = chips
    assert chris["sf"] == 87 and chris["lc0"] is None
    assert alice["sf"] is None and alice["lc0"] == 80
```

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest games/tests/test_game_format_tags.py -q
```

- [ ] **Step 4: Implement**

Create `services/app/games/templatetags/game_format.py`:

```python
"""
Title: game_format.py — Template tags for the search results table and modal
Description:
    Filters and inclusion-tag helpers used by ``templates/search/`` to
    render human time controls, truncated opening notation, accuracy
    bands, and club-member accuracy chips on the search results table
    and the game preview modal.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

from django import template

from games.opening_notation import opening_notation as _opening_notation
from games.time_control_format import format_time_control

register = template.Library()


@register.filter(name="time_control_human")
def time_control_human(game) -> str:
    """Render a Game's time control as a human label.

    Reads ``time_control_base_s``, ``time_control_increment_s``, and the
    raw ``time_control`` string as a fallback.
    """
    return format_time_control(
        getattr(game, "time_control_base_s", None),
        getattr(game, "time_control_increment_s", None),
        raw=getattr(game, "time_control", "") or "",
    )


@register.filter(name="opening_notation")
def opening_notation_filter(pgn_text: str, max_plies: int = 10) -> str:
    """Render the first ``max_plies`` plies of a PGN as SAN."""
    return _opening_notation(pgn_text or "", max_plies=max_plies)


_BANDS = (
    (90, "wc-chip--band-strong"),
    (80, "wc-chip--band-good"),
    (70, "wc-chip--band-fair"),
    (60, "wc-chip--band-weak"),
)


@register.filter(name="accuracy_band_class")
def accuracy_band_class(accuracy) -> str:
    """Return the Tailwind chip class for an accuracy value.

    ``None`` → unknown; ``<60`` → poor. The colour-token bindings live
    in tailwind.config.js (forest/moss/honey/rust/clay).
    """
    if accuracy is None:
        return "wc-chip wc-chip--band-unknown"
    for floor, cls in _BANDS:
        if accuracy >= floor:
            return f"wc-chip {cls}"
    return "wc-chip wc-chip--band-poor"


def _avg(*vals):
    """Mean of the non-None inputs, or ``None`` if all are ``None``."""
    present = [v for v in vals if v is not None]
    return sum(present) / len(present) if present else None


def club_accuracy_chips(
    *,
    white_username: str | None,
    black_username: str | None,
    club_usernames: dict[str, str],
    sf_white: float | None,
    sf_black: float | None,
    lc0_white: float | None,
    lc0_black: float | None,
) -> list[dict]:
    """Build chip data for each side that is a club member.

    Args:
        white_username, black_username: Game's recorded usernames.
        club_usernames: Mapping of ``username → display_name`` for club
            members (case-insensitive on key).
        sf_white, sf_black, lc0_white, lc0_black: Per-side accuracy
            percentages; ``None`` when the engine has no data.

    Returns:
        A list with one dict per club-member side (zero, one, or two
        entries). Each dict has keys ``display_name``, ``sf``, ``lc0``,
        ``band_class``. Missing engine values stay ``None`` so the
        template can omit them.
    """
    club_lower = {k.lower(): v for k, v in (club_usernames or {}).items()}
    out: list[dict] = []
    for username, sf, lc0 in (
        (white_username, sf_white, lc0_white),
        (black_username, sf_black, lc0_black),
    ):
        if not username:
            continue
        display = club_lower.get(username.lower())
        if not display:
            continue
        avg = _avg(sf, lc0)
        out.append({
            "display_name": display,
            "sf": sf,
            "lc0": lc0,
            "band_class": accuracy_band_class(avg),
        })
    return out


@register.simple_tag(name="club_accuracy_chips")
def club_accuracy_chips_tag(*, white_username, black_username, club_usernames,
                             sf_white=None, sf_black=None,
                             lc0_white=None, lc0_black=None):
    """Template wrapper around ``club_accuracy_chips``."""
    return club_accuracy_chips(
        white_username=white_username,
        black_username=black_username,
        club_usernames=club_usernames,
        sf_white=sf_white,
        sf_black=sf_black,
        lc0_white=lc0_white,
        lc0_black=lc0_black,
    )
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest games/tests/test_game_format_tags.py -q
```

- [ ] **Step 6: Add Tailwind chip styles**

Open `services/app/tailwind.css` (or the project's tailwind input — confirm via `grep -l "@layer components" services/app/`).

Append to the `@layer components` block:

```css
  .wc-chip {
    @apply inline-flex items-center gap-2 px-2.5 py-1 rounded
           font-mono text-xs whitespace-nowrap;
  }
  .wc-chip--band-strong  { @apply bg-forest text-parchment; }
  .wc-chip--band-good    { @apply bg-moss text-parchment; }
  .wc-chip--band-fair    { @apply bg-honey text-ebony; }
  .wc-chip--band-weak    { @apply bg-rust text-parchment; }
  .wc-chip--band-poor    { @apply bg-clay text-parchment; }
  .wc-chip--band-unknown { @apply bg-parchment text-slate border border-peat/30; }
```

Verify the colour tokens exist:

```bash
grep -E "forest|moss|honey|rust|clay|parchment|peat|slate" services/app/tailwind.config.js | head -20
```

If `moss`, `honey`, `rust`, or `clay` is **missing** from the palette, add the closest existing token instead (e.g. replace `moss`→`forest/80`, `honey`→`honey` (rename), `rust`→`peat`, `clay`→`clay` (rename)). Match what's present in the codebase rather than inventing new tokens. Note the substitution in the commit message.

- [ ] **Step 7: Rebuild Tailwind**

```bash
cd services/app
./bin/build_tailwind.sh
```

- [ ] **Step 8: Bandit + commit**

```bash
bandit -ll games/templatetags/game_format.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/games/templatetags/ services/app/games/tests/test_game_format_tags.py \
        services/app/tailwind.css services/app/staticfiles/css/tailwind.css 2>/dev/null
git commit -m "feat(#162): template tags + wc-chip accuracy bands

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Reusable `wc-modal` component (frontend-design dispatch)

**Files:**
- Create: `services/app/templates/components/_modal.html`
- Create: `services/app/static/js/wc_modal.js`
- Modify: `services/app/templates/base.html` (load modal CSS class + JS)
- Modify: `services/app/tailwind.css` (`.wc-modal` styles)

This task is dispatched to a **Sonnet subagent invoking the `frontend-design` skill** so the visual treatment is consistent. The subagent receives this brief; the file layout above is mandatory output.

**Subagent brief (paste this into the Agent prompt):**

> Use the `frontend-design` skill to design a reusable Tailwind+HTMX modal component for the Wood League Chess Django app. Palette tokens: parchment (bg), ebony (text), forest (accent), peat (border), clay (warning). Fonts: serif headlines, mono metadata.
>
> Deliver exactly three files:
>
> 1. `services/app/templates/components/_modal.html` — a Django partial with a backdrop `<div>` and panel `<div>`, an `id` attribute taken from a template variable, a close button (`.wc-modal-close`, ✕ glyph top-right), and a `{% block modal_body %}{% endblock %}` slot. The shell starts hidden (`hidden` class) and is shown by adding the `wc-modal--open` class. Markup must be HTMX-friendly: the panel inner content is replaced by `hx-swap="innerHTML"` from outside. Provide a `{% include "components/_modal.html" with modal_id="search-modal" %}` example in a leading comment.
>
> 2. `services/app/static/js/wc_modal.js` — a tiny ES-module-free controller (≈40 LoC). Watches `document` for clicks on `[data-wc-modal-open]` (opens the modal whose id is in the attribute), clicks on `.wc-modal-close` or the backdrop (closes), and `Escape` keydown (closes top-most open modal). Exposes a `window.WcModal.open(id)` and `WcModal.close(id)` API. Triggers `wc-modal:opened` / `wc-modal:closed` CustomEvents. Listens for `htmx:afterSwap` on any element inside a `.wc-modal` panel and auto-opens its enclosing modal.
>
> 3. Tailwind additions appended to `services/app/tailwind.css` under `@layer components`:
>    - `.wc-modal` — fixed inset-0, hidden by default, z-50, flex centred.
>    - `.wc-modal--open` — display flex, fade-in.
>    - `.wc-modal__backdrop` — absolute inset-0, bg-ebony/60.
>    - `.wc-modal__panel` — relative bg-parchment border border-peat/40 shadow-xl max-w-2xl w-full mx-4 p-6, max-h-[90vh] overflow-y-auto.
>    - `.wc-modal__close` — absolute top-3 right-3, font-mono, text-slate hover:text-ebony.
>
> Also modify `services/app/templates/base.html` to add `<script src="{% static 'js/wc_modal.js' %}" defer></script>` to the head/body bottom and to render an always-present `#search-modal` placeholder by `{% include "components/_modal.html" with modal_id="search-modal" %}` near `</body>`.
>
> Constraints:
> - No Alpine.js, no extra deps.
> - Total JS ≤ 60 lines.
> - All file headers must include Title/Description/Changelog blocks (project convention).
> - Run `services/app/bin/build_tailwind.sh` after editing tailwind.css.
> - Commit on the existing `issue/162-search-page-rework` branch with message: `feat(#162): reusable wc-modal component`.
>
> Do not modify any other file. When done, report files changed and any palette substitutions made.

- [ ] **Step 1: Dispatch the subagent**

```
Agent(
  description="Build wc-modal component",
  subagent_type="general-purpose",
  model="sonnet",
  prompt=<above brief>
)
```

- [ ] **Step 2: Verify subagent's commit landed**

```bash
git log --oneline -1
git show --stat HEAD
```

Expect three new/modified files: `_modal.html`, `wc_modal.js`, `base.html`, plus tailwind regen.

- [ ] **Step 3: Quick smoke**

```bash
cd services/app
python manage.py check
./bin/build_tailwind.sh
```

- [ ] **Step 4: Manual sanity** — start dev server and click anywhere on the home page; modal should not appear by default. Open devtools console, run `WcModal.open('search-modal')` — placeholder modal should appear, Esc should close it.

---

## Task 10: New AI prompt rules + `current_user_username` plumbing

**Files:**
- Modify: `services/app/search/services.py`
- Test: `services/app/search/tests/test_services_prompt.py` (create)

- [ ] **Step 1: Ensure search tests dir exists**

```bash
cd services/app
[ -d search/tests ] || (mkdir search/tests && touch search/tests/__init__.py)
```

- [ ] **Step 2: Write failing tests**

Create `services/app/search/tests/test_services_prompt.py`:

```python
"""
Title: test_services_prompt.py — Assert new AI prompt directives are present
Description: String-match checks that the system prompt assembled by
    generate_search_plan teaches self-reference, name mapping, and club
    vocabulary rules.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from unittest import mock

import pytest

from search import services


@pytest.mark.django_db
def test_schema_context_mentions_club_vocab():
    text = services._schema_context()
    assert "club games" in text.lower()
    assert "club member" in text.lower() or "club players" in text.lower()


@pytest.mark.django_db
def test_generate_search_plan_threads_current_user(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self_inner):
                return {"content": [{"type": "text",
                    "text": '{"sql_query": "SELECT 1 FROM games LIMIT 1", "reasoning": "ok"}'}]}
        return R()

    monkeypatch.setattr(services.requests, "post", fake_post)
    monkeypatch.setattr(services.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)

    services.generate_search_plan("show my games", current_user_username="chris")

    user_msg = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "chris" in user_msg.lower()


@pytest.mark.django_db
def test_generate_search_plan_anonymous_omits_self_rule(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        class R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self_inner):
                return {"content": [{"type": "text",
                    "text": '{"sql_query": "SELECT 1 FROM games LIMIT 1", "reasoning": "ok"}'}]}
        return R()

    monkeypatch.setattr(services.requests, "post", fake_post)
    monkeypatch.setattr(services.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)

    services.generate_search_plan("show recent games", current_user_username=None)
    user_msg = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "current user" not in user_msg.lower()
```

- [ ] **Step 3: Run, expect FAIL**

```bash
pytest search/tests/test_services_prompt.py -q
```

- [ ] **Step 4: Edit `services/app/search/services.py`**

Inside `_schema_context()`, append before the closing triple-quoted return:

```
CLUB VOCABULARY:
- "club games" — games where BOTH white_username AND black_username appear in the
  KNOWN CLUB PLAYERS list (see the next system block).
- "people in the club", "part of the club", "club member", "club players" — players
  whose username appears in that list.
- "I", "me", "my", "my games", "mine", "myself" — when a "current_user_username"
  is supplied in the user message, treat that username as the player. If no
  current_user_username is supplied, return reasoning that explains the request
  needs a signed-in user and an empty SELECT.

NAME MAPPING:
- Player names (first names, display names, real names, possessive forms) MUST
  resolve to a username in the KNOWN CLUB PLAYERS list. If a name does not
  appear there, return a reasoning that says so and an empty SELECT (still
  valid SQL such as `SELECT id, slug FROM games WHERE 1=0`).
```

Change `generate_search_plan` signature:

```python
def generate_search_plan(user_query: str, *, current_user_username: str | None = None) -> SearchPlan:
```

Update its user-message construction to inject the current user inline:

```python
    suffix = ""
    if current_user_username:
        suffix = f"\n\ncurrent_user_username: {current_user_username}"
    user_text = f"User request:\n{user_query}{suffix}\n\nReturn only JSON with sql_query and reasoning."
    payload = {
        ...
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": user_text}]},
        ],
    }
```

(Keep `_schema_context` and `_player_directory_context` in the cached `system` blocks unchanged in cache-key shape so the cache still hits.)

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest search/tests/test_services_prompt.py -q
```

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll search/services.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/search/services.py services/app/search/tests/
git commit -m "feat(#162): AI prompt — club vocab, name mapping, self-ref

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Search view + URL — pass user, add modal partial endpoint

**Files:**
- Modify: `services/app/search/views.py`
- Modify: `services/app/search/urls.py`
- Test: `services/app/search/tests/test_views.py`

- [ ] **Step 1: Write failing test**

Create `services/app/search/tests/test_views.py`:

```python
"""
Title: test_views.py — search view behaviour
Description: Asserts copy changes, current_user_username threading, and the
    new modal partial endpoint.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest
from unittest import mock

from django.urls import reverse

from accounts.models import User
from games.models import Game
from players.models import Player


@pytest.mark.django_db
def test_search_index_uses_new_copy(client):
    resp = client.get(reverse("search_index"))
    body = resp.content.decode()
    assert "Find club games" in body
    assert "validated SQL" not in body
    assert "King's Pawn" in body  # new example text


@pytest.mark.django_db
def test_ai_partial_passes_current_user(client):
    user = User.objects.create_user(email="chris@example.com", password="x")
    Player.objects.create(username="chris", display_name="Chris",
                          email="chris@example.com")
    client.force_login(user)
    with mock.patch("search.views.generate_search_plan") as gp:
        gp.return_value = mock.Mock(sql_query="SELECT id, slug FROM games LIMIT 1",
                                    reasoning="ok")
        with mock.patch("search.views.execute_sql_search", return_value=[]):
            client.post(reverse("search_ai_partial"),
                        {"query": "my recent losses"})
    args, kwargs = gp.call_args
    assert kwargs.get("current_user_username") == "chris"


@pytest.mark.django_db
def test_game_modal_partial(client):
    g = Game.objects.create(id="m1", slug="m-1",
                            white_username="chris", black_username="alice",
                            pgn="[Event \"t\"]\n\n1. e4 e5 *",
                            result_pgn="1-0", winner_username="chris")
    resp = client.get(reverse("search_game_modal_partial", args=[g.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "chris" in body and "alice" in body
    assert "OPEN ANALYSIS" in body
```

- [ ] **Step 2: Run, expect FAIL**

```bash
pytest search/tests/test_views.py -q
```

- [ ] **Step 3: Edit `services/app/search/views.py`**

Top of file, add imports:

```python
from accounts.services import resolve_current_player
from players.models import Player
```

Replace `ai_search_partial` body so it threads the current user:

```python
def ai_search_partial(request):
    """Execute AI-generated SQL search from natural language query (HTMX partial)."""
    query = request.POST.get("query", "").strip()
    if not query:
        return render(request, "search/partials/results.html", {
            "error": "Please enter a search query.",
            "results": [],
        })
    player = resolve_current_player(request.user)
    current_user_username = player.username if player else None
    try:
        plan = generate_search_plan(query, current_user_username=current_user_username)
        results = execute_sql_search(plan.sql_query)
        return render(request, "search/partials/results.html", {
            "results": _enrich(_normalise(results)),
            "sql": plan.sql_query,
            "reasoning": plan.reasoning,
            "debug": settings.DEBUG,
            "club_usernames": _club_usernames(),
        })
    except SearchPlanError as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "sql": exc.candidate_sql,
            "reasoning": exc.reasoning,
            "results": [],
            "debug": settings.DEBUG,
        })
    except Exception as exc:
        return render(request, "search/partials/results.html", {
            "error": str(exc),
            "results": [],
            "debug": settings.DEBUG,
        })
```

Update `keyword_search_partial` similarly to pass `debug` and `club_usernames`.

Add `_enrich` and `_club_usernames` helpers:

```python
def _club_usernames() -> dict[str, str]:
    """Map of {username: display_name} for all known club Players."""
    return dict(
        Player.objects.values_list("username", "display_name")
    )


def _enrich(rows: list[dict]) -> list[dict]:
    """Hydrate result rows with Game-derived fields the new table needs.

    Adds: time_control_base_s, time_control_increment_s, time_control,
    opening_id, opening_name (best label), pgn (for opening_notation),
    move_count, winner_username, white_rating, black_rating, and
    per-side accuracies (sf_white, sf_black, lc0_white, lc0_black).
    """
    if not rows:
        return rows
    ids = [r["game_id"] for r in rows if r.get("game_id")]
    games = {g.id: g for g in Game.objects.filter(id__in=ids).select_related(
        "opening", "analysis", "lc0_analysis",
    )}
    out = []
    for r in rows:
        g = games.get(r.get("game_id"))
        if g is None:
            out.append(r)
            continue
        sf = getattr(g, "analysis", None)
        lc = getattr(g, "lc0_analysis", None)
        r.update({
            "time_control_base_s": g.time_control_base_s,
            "time_control_increment_s": g.time_control_increment_s,
            "time_control": g.time_control,
            "opening_id": g.opening_id,
            "opening_name": g.lichess_opening or g.opening_name or "",
            "pgn": g.pgn or "",
            "winner_username": g.winner_username or "",
            "white_rating": g.white_rating,
            "black_rating": g.black_rating,
            "result_pgn": g.result_pgn or "",
            "move_count": _move_count(g.pgn or ""),
            "sf_white": getattr(sf, "white_accuracy", None),
            "sf_black": getattr(sf, "black_accuracy", None),
            "lc0_white": getattr(lc, "white_accuracy", None),
            "lc0_black": getattr(lc, "black_accuracy", None),
        })
        out.append(r)
    return out


def _move_count(pgn_text: str) -> int | None:
    """Return number of full moves (pairs) parsed from ``pgn_text`` or None."""
    if not pgn_text:
        return None
    try:
        import io, chess.pgn
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return None
        plies = sum(1 for _ in game.mainline_moves())
        return (plies + 1) // 2
    except Exception:  # noqa: BLE001
        return None
```

Add new `game_modal_partial`:

```python
def game_modal_partial(request, game_id):
    """Render the game preview modal body (HTMX partial)."""
    try:
        game = Game.objects.select_related(
            "opening", "analysis", "lc0_analysis",
        ).get(id=game_id)
    except Game.DoesNotExist:
        return HttpResponse(
            "<p class='font-mono text-xs text-slate'>Game not found.</p>",
            status=404,
        )
    pgn_text = (game.pgn or "").strip()
    board_html = _board_animation_html(pgn_text)
    return render(request, "search/partials/game_modal.html", {
        "game": game,
        "board_html": board_html,
        "club_usernames": _club_usernames(),
        "sf": getattr(game, "analysis", None),
        "lc": getattr(game, "lc0_analysis", None),
    })
```

- [ ] **Step 4: Edit `services/app/search/urls.py`** — add:

```python
path("modal/<str:game_id>/", views.game_modal_partial,
     name="search_game_modal_partial"),
```

Keep `search_board_partial` for now to avoid breaking other callers; remove only after Task 13 confirms no template references it.

- [ ] **Step 5: Run tests, expect PASS**

```bash
pytest search/tests/test_views.py -q
```

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll search/views.py
cd /Users/christopherwebster/Projects/wood_league
git add services/app/search/views.py services/app/search/urls.py services/app/search/tests/test_views.py
git commit -m "feat(#162): search view threads user + game_modal_partial

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Rework `templates/search/index.html` copy + tab placeholders

**Files:**
- Modify: `services/app/templates/search/index.html`

- [ ] **Step 1: Apply edits**

Replace the page-hero block and AI panel as follows:

```html
<div class="page-hero">
  <div>
    <h1>Find club games</h1>
  </div>
</div>

{# ── Mode tabs ─────────────────────────────────────────────────────────── #}
<div class="tab-bar" id="search-tabs">
  <button id="tab-ai" class="tab-btn search-tab tab-btn--active"
          onclick="switchTab('ai')"
          {% if not ai_available %}disabled title="ANTHROPIC_API_KEY not configured"{% endif %}>
    AI Search
  </button>
  <button id="tab-kw" class="tab-btn search-tab" onclick="switchTab('kw')">
    Keyword
  </button>
</div>

<div id="panel-ai" class="search-panel">
  {% if not ai_available %}
  <p class="font-mono text-xs text-peat mb-3">
    ANTHROPIC_API_KEY not configured — AI search unavailable.
  </p>
  {% endif %}
  <form hx-post="{% url 'search_ai_partial' %}"
        hx-target="#search-results"
        hx-indicator="#search-spinner"
        class="flex gap-2 mb-3">
    {% csrf_token %}
    <input type="text" name="query"
           placeholder="Show me the games I've won playing a King's Pawn opening against players with an ELO higher than mine."
           class="wc-input" style="flex:1;"
           {% if not ai_available %}disabled{% endif %}>
    <button type="submit" class="wc-btn wc-btn-solid"
            {% if not ai_available %}disabled{% endif %}>
      Search
    </button>
  </form>
</div>
```

Remove the old "Describe games in plain English — the app generates validated SQL and runs it." paragraph entirely.

At the bottom (before `{% endblock %}`), include the modal placeholder if `base.html` does not already render one:

```html
{% include "components/_modal.html" with modal_id="search-modal" %}
```

(Skip this `{% include %}` if Task 9's subagent already put it in `base.html`.)

- [ ] **Step 2: Smoke**

```bash
cd services/app
python manage.py check
pytest search/tests/test_views.py::test_search_index_uses_new_copy -q
```

- [ ] **Step 3: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/templates/search/index.html
git commit -m "feat(#162): search page copy — 'Find club games'

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: New results table + modal-triggering rows

**Files:**
- Modify: `services/app/templates/search/partials/results.html`

- [ ] **Step 1: Replace file contents**

```html
{% load game_format %}

{% if error %}
<div class="border border-peat/40 bg-cream p-4 mb-4 font-mono text-sm text-peat">
  {{ error }}
  {% if debug and sql %}<pre class="mt-2 text-xs overflow-x-auto text-slate">{{ sql }}</pre>{% endif %}
</div>
{% endif %}

{% if debug %}
  {% if reasoning %}
  <details class="mb-2">
    <summary class="font-mono text-xs text-slate cursor-pointer hover:text-forest">Reasoning</summary>
    <p class="font-mono text-xs text-slate mt-1">{{ reasoning }}</p>
  </details>
  {% endif %}
  {% if sql and not error %}
  <details class="mb-3">
    <summary class="font-mono text-xs text-slate cursor-pointer hover:text-forest">Show SQL</summary>
    <pre class="font-mono text-xs text-slate mt-1 overflow-x-auto border border-peat/20 p-2 bg-cream">{{ sql }}</pre>
  </details>
  {% endif %}
{% endif %}

{% if results %}
<p class="font-mono text-xs text-slate mb-2">{{ results|length }} game{{ results|length|pluralize }} found</p>
<div class="overflow-x-auto">
  <table class="wc-table wc-table--zebra w-full">
    <thead>
      <tr>
        <th class="text-left">Game</th>
        <th class="text-left">Time</th>
        <th class="text-left">Date</th>
        <th class="text-left">Opening</th>
        <th class="text-left">Moves</th>
      </tr>
    </thead>
    <tbody>
      {% for row in results %}
      <tr class="cursor-pointer hover:bg-parchment/60 transition-colors"
          hx-get="{% url 'search_game_modal_partial' row.game_id %}"
          hx-target="#search-modal .wc-modal__panel-body"
          hx-swap="innerHTML"
          hx-indicator="#search-spinner"
          data-wc-modal-open="search-modal">
        <td class="font-serif text-sm">
          {{ row.white_username }}{% if row.white_rating %} ({{ row.white_rating }}){% endif %}
          v.
          {{ row.black_username }}{% if row.black_rating %} ({{ row.black_rating }}){% endif %}
          {% if row.winner_username == row.white_username %} 🏆{% endif %}
          {% if row.winner_username == row.black_username %} 🏆{% endif %}
        </td>
        <td class="font-mono text-xs whitespace-nowrap">
          {{ row|time_control_human }}
        </td>
        <td class="font-mono text-xs text-peat whitespace-nowrap">{{ row.played_at }}</td>
        <td class="font-mono text-xs text-slate max-w-md truncate">
          {{ row.pgn|opening_notation }}
        </td>
        <td class="font-mono text-xs">{{ row.move_count|default:"—" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% elif not error %}
<p class="font-mono text-sm text-slate">No games matched.</p>
{% endif %}
```

Note: `row|time_control_human` works because the filter reads attributes via `getattr`; the dict rows expose them too because `_enrich` populates them. The filter must tolerate dicts; verify Task 8 handles `getattr` on a dict (Django's `getattr` falls back to `__getitem__` automatically). If not, switch the filter to read `r.get(...)` for dicts.

- [ ] **Step 2: Fix the filter for dicts if needed**

If smoke test in Step 3 fails on `time_control_human`, edit `services/app/games/templatetags/game_format.py`:

```python
def time_control_human(game) -> str:
    """..."""
    def _g(name):
        if isinstance(game, dict):
            return game.get(name)
        return getattr(game, name, None)
    return format_time_control(_g("time_control_base_s"),
                               _g("time_control_increment_s"),
                               raw=_g("time_control") or "")
```

- [ ] **Step 3: Smoke**

```bash
cd services/app
python manage.py check
pytest search/tests/test_views.py -q
```

- [ ] **Step 4: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/templates/search/partials/results.html services/app/games/templatetags/game_format.py
git commit -m "feat(#162): new search results table — title/time/date/opening/moves

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Game-modal partial template

**Files:**
- Create: `services/app/templates/search/partials/game_modal.html`

- [ ] **Step 1: Write the template**

Create `services/app/templates/search/partials/game_modal.html`:

```html
{% load game_format %}

<div class="space-y-4">
  {# Headline #}
  <h2 class="font-serif text-2xl text-ebony">
    {{ game.white_username }}{% if game.white_rating %} ({{ game.white_rating }}){% endif %}
    v.
    {{ game.black_username }}{% if game.black_rating %} ({{ game.black_rating }}){% endif %}
    {% if game.winner_username == game.white_username %} 🏆{% endif %}
    {% if game.winner_username == game.black_username %} 🏆{% endif %}
  </h2>

  {# Opening — linked if we resolved an id #}
  {% if game.opening_id %}
  <a href="{% url 'openings:detail' game.opening_id %}"
     class="font-serif text-lg text-forest hover:underline">
    {{ game.lichess_opening|default:game.opening_name }}
  </a>
  {% elif game.lichess_opening or game.opening_name %}
  <p class="font-serif text-lg text-ebony">{{ game.lichess_opening|default:game.opening_name }}</p>
  {% endif %}

  {# Meta line #}
  <p class="font-mono text-xs text-slate">
    {% if game.played_at %}{{ game.played_at|date:"d M Y" }}{% endif %}
    {% if game.time_control_base_s or game.time_control %} · {{ game|time_control_human }}{% endif %}
  </p>

  {# Club-member accuracy chips #}
  {% club_accuracy_chips
      white_username=game.white_username
      black_username=game.black_username
      club_usernames=club_usernames
      sf_white=sf.white_accuracy
      sf_black=sf.black_accuracy
      lc0_white=lc.white_accuracy
      lc0_black=lc.black_accuracy
    as chips %}
  {% if chips %}
  <div class="flex flex-wrap gap-2">
    {% for chip in chips %}
    <span class="{{ chip.band_class }}">
      {{ chip.display_name }}:
      {% if chip.sf is not None %}SF {{ chip.sf|floatformat:0 }}%{% endif %}
      {% if chip.sf is not None and chip.lc0 is not None %} · {% endif %}
      {% if chip.lc0 is not None %}Lc0 {{ chip.lc0|floatformat:0 }}%{% endif %}
    </span>
    {% endfor %}
  </div>
  {% endif %}

  {# Analysis CTA #}
  {% if game.slug %}
  <a href="{% url 'games:analysis' game.slug %}"
     class="inline-block border border-forest text-forest font-mono text-xs uppercase tracking-wide px-3 py-1 hover:bg-forest hover:text-parchment transition-colors">
    OPEN ANALYSIS →
  </a>
  {% endif %}

  {# Animated board #}
  {% if board_html %}
  <div>{{ board_html|safe }}</div>
  {% else %}
  <p class="font-mono text-xs text-slate">No PGN available for this game.</p>
  {% endif %}
</div>
```

- [ ] **Step 2: Adjust modal panel body target**

The HTMX `hx-target` in Task 13 points at `#search-modal .wc-modal__panel-body`. Open `services/app/templates/components/_modal.html` (from Task 9) and ensure the panel inner wrapper has class `wc-modal__panel-body`. If the subagent named it differently (e.g. `wc-modal__content`), either:

- Edit the modal template to use `wc-modal__panel-body`, or
- Edit Task 13's `hx-target` to match. Pick one and apply.

- [ ] **Step 3: Smoke**

```bash
cd services/app
python manage.py check
pytest search/tests/test_views.py::test_game_modal_partial -q
```

- [ ] **Step 4: Manual modal trial**

Start the dev server, log in, run a keyword search that returns ≥1 row, click a row. Modal opens, shows the new layout, Esc closes it.

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/app/templates/search/partials/game_modal.html services/app/templates/components/_modal.html
git commit -m "feat(#162): game preview modal partial with accuracy chips

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Production backfill + remove dead side-panel preview

**Files:**
- Modify: `services/app/search/urls.py` (remove old route)
- Modify: `services/app/search/views.py` (remove `board_preview_partial`)
- Delete: `services/app/templates/search/partials/board_preview.html`

- [ ] **Step 1: Confirm no template still references the old route**

```bash
cd services/app
grep -rn "search_board_partial\|board-preview-panel" templates/ static/
```

Expect zero matches. If any remain from Task 13 cleanup, fix them first.

- [ ] **Step 2: Remove**

```bash
git rm services/app/templates/search/partials/board_preview.html
```

In `services/app/search/views.py`, delete the `board_preview_partial` function.
In `services/app/search/urls.py`, delete the `search_board_partial` path.

- [ ] **Step 3: Run full search suite**

```bash
pytest search/ games/ accounts/ -q
```

- [ ] **Step 4: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add -A
git commit -m "chore(#162): remove obsolete side-panel board preview

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Run the backfill in dev**

```bash
cd services/app && python manage.py backfill_opening_ids
```

Verify the output reports resolved > 0 unless the dev DB is empty.

---

## Task 16: Wiki page — Search

**Files:**
- Modify: `wood_league.wiki/Search.md` (create if absent)

- [ ] **Step 1: Write the page**

Open `wood_league.wiki/Search.md` and replace / create with plain non-technical prose:

```markdown
# Search

Find club games by typing a natural-language question, or with a simple keyword search.

## AI search

Type any question about games and the app turns it into a database query for you. You can say things like:

- "Show me the games I've won playing a King's Pawn opening against players with an ELO higher than mine."
- "Bob's draws in the last month."
- "Club games where someone won in under 25 moves."

### Words the AI understands

| You write | The AI interprets it as |
| --- | --- |
| `I`, `me`, `my`, `mine`, `myself` | The player matching your signed-in account. |
| `club games` | Games where both players are club members. |
| `people in the club`, `club players`, `club member` | Any player listed on [[Players]]. |
| A first name, last name or display name | The matching club username. |

If the AI can't match a name to a club member it will say so and return nothing.

## Keyword search

Searches across player names, opening names, ECO codes and time controls. Plain substring match — no special syntax.

## Reading the results

| Column | What it shows |
| --- | --- |
| **Game** | `White (rating) v. Black (rating)` with a 🏆 next to the winner. |
| **Time** | Human-readable time control — `15+10 min`, `1 day per move`, `3 min`. |
| **Date** | When the game was played. |
| **Opening** | The first few moves in chess notation, e.g. `1. e4 e5 2. Nf3 Nc6 3. Bb5`. |
| **Moves** | Total number of full moves in the game. |

Click any row to open the **game preview** — see [[Game preview]] below.

## Game preview

Clicking a row opens a card with everything you need to decide whether to dive into the full analysis:

- The headline (players, ratings, winner trophy).
- The **opening name** — links straight to its [[Openings]] page.
- Date and time control.
- **Accuracy chips** for each club-member side, one per player. Each chip shows that player's Stockfish and Lc0 accuracy as a percentage, colour-coded:
  - Strong green — 90%+
  - Green — 80–89%
  - Amber — 70–79%
  - Orange — 60–69%
  - Red — below 60%
- An **Open analysis** button — see [[Analysis]] for the full board, move list and engine breakdown.
- An animated board you can scrub through.

Press Esc, click outside the card, or use the ✕ button to dismiss it.

## See also

- [[Players]]
- [[Openings]]
- [[Analysis]]
```

- [ ] **Step 2: Commit in the wiki repo**

```bash
cd /Users/christopherwebster/Projects/wood_league.wiki
git add Search.md
git commit -m "docs: search page rework (#162)"
git push
```

- [ ] **Step 3: Back to main repo**

```bash
cd /Users/christopherwebster/Projects/wood_league
```

---

## Task 17: Final verification

- [ ] **Step 1: Quality gate**

```bash
source .venv/bin/activate
cd services/app
ruff check .
ruff format --check .
mypy .
pytest games/ search/ accounts/ openings/ -q --cov=games --cov=search --cov=accounts
./bin/build_tailwind.sh
python manage.py check
```

- [ ] **Step 2: Bandit on every edited Python file**

```bash
bandit -ll \
  games/time_control_format.py \
  games/opening_notation.py \
  games/opening_resolver.py \
  games/templatetags/game_format.py \
  games/management/commands/backfill_opening_ids.py \
  accounts/services.py \
  search/services.py \
  search/views.py
```

Fix any Medium/High findings.

- [ ] **Step 3: Manual end-to-end**

1. `python manage.py runserver` (dev), log in.
2. `/search/` — copy reads "Find club games"; no "validated SQL" anywhere; example placeholder updated.
3. Type "show me my recent losses" → results appear with new table columns.
4. Click a row → modal opens, shows headline, opening link, chips, board.
5. Click outside / press Esc → modal closes.
6. In keyword mode, repeat the row click; same modal behaviour.
7. With `DEBUG=False` (set in `.env` temporarily), refresh `/search/` and re-run a query — Reasoning and SQL controls absent.

- [ ] **Step 4: Push + PR**

```bash
git push -u origin issue/162-search-page-rework
gh pr create --title "feat(#162): search page rework" \
  --body "Closes #162.

Spec: docs/superpowers/specs/2026-05-20-search-page-rework-design.md
Plan: docs/superpowers/plans/2026-05-20-search-page-rework.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 5: Production rollout note**

After merge, run on prod:

```bash
python manage.py migrate games
python manage.py backfill_opening_ids
```

Document this in the PR description's "deploy steps" section.

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task(s) |
| --- | --- |
| Headline → "Find club games" | 12 |
| Remove "validated SQL" tagline | 12 |
| Humanised example text | 12 |
| Hide SQL / collapse Reasoning unless DEBUG | 13 |
| AI prompt: self-reference (I/me/my/mine) | 10 |
| AI prompt: name mapping via players directory | 10 |
| AI prompt: club / club games vocabulary | 10 |
| Game.opening FK at ingest + backfill | 4, 5, 6, 15 |
| Table cols: title with trophy, time, date, opening notation, moves | 11, 13 |
| Modal card replaces side panel | 9, 11, 14, 15 |
| Opening common-name link | 14 |
| Date + time control in modal | 14 |
| Club-member accuracy chips with colour bands | 8, 14 |
| OPEN ANALYSIS button | 14 |
| Animated board in modal | 14 |
| Easy modal dismissal (backdrop / Esc / ✕) | 9 |
| Reusable modal pattern | 9 |
| Wiki Search page update | 16 |
| Routing — Haiku/Sonnet per global standard | Tasks 1-2-6-16 Haiku; 3-4-5-7-8-9-10-11-13-14 Sonnet |

**Placeholder scan:** No "TBD" / "implement later" / vague handwaves. Every code step has the actual code.

**Type consistency:**
- `format_time_control(base, inc, *, raw=None)` — same signature used in tag (Task 8).
- `opening_notation(pgn, max_plies=10)` — same in tests (Task 2), in tag (Task 8), in template (Task 13).
- `resolve_opening_id(pgn_text)` — same in resolver (Task 3), ingest (Task 5), backfill (Task 6).
- `resolve_current_player(user) -> Player | None` — used in Task 11.
- `generate_search_plan(user_query, *, current_user_username=None)` — Task 10 defines, Task 11 passes kwarg.
- `_club_usernames()` — Task 11 defines, Tasks 13 + 14 consume via context.
- Modal panel inner: Task 14 makes its target match whatever Task 9 chose (`.wc-modal__panel-body`).

All resolved. Plan is ready.
