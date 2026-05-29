# Game Detail Page — Header, Opening/Book Context & PGN Actions (#226) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the game detail page header human-readable (friendly time control, opening common-name link, Open-on-chess.com + Copy-PGN buttons, winner trophy), surface "book" (opening-theory) moves distinctly on the SF & LC0 charts and the "This Move" panel, and auto-collapse the Moves PGN block.

**Architecture:** A single PGN walk (`book_context`) reuses `openings.services.lookup_opening_entry` to resolve the deepest opening (id + common name) and the leading book-ply count. `GameAnalysisDataV2` carries four new derived fields (`time_control_label`, `opening_book_id`, `opening_common_name`, `book_ply_count`, plus `winner_username` + winner properties). Chart payloads and the chips/"This Move" context gain a per-ply `book` flag; the templates and chart JS render the new affordances. No DB/model/migration changes — everything derives from existing columns + PGN.

**Tech Stack:** Django 5 + templates + HTMX, python-chess, Plotly (vanilla JS charts), pytest. Worktree: `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+226-game-detail-header-book` on branch `worktree-issue+226-game-detail-header-book`.

**Decisions (confirmed with user):**
1. PGN button = **copy to clipboard** (not file download).
2. Time-control label format = **`"<Class> · <body>"`** e.g. `"Rapid · 10+5 min"`, `"Daily · 3 days per move"`.
3. Chart book tooltip = **plain hover text** `"Book — <Opening name>"` (no custom-HTML clickable tooltip); the clickable opening link lives in the header + "This Move" panel.

**Test/quality conventions:**
- Run everything from `services/app/` with the **main-repo venv**: `source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate`.
- Tests need the symlinked `services/app/.env.test` (dev test Postgres). New tests go in `games/tests/test_<mod>.py` (NEVER `games/tests.py` — it is dead/shadowed).
- A per-edit quality-gate hook runs ruff + mypy + pytest + complexity on each `.py` you save; expect transient failures mid-TDD. After editing any `.py`, also run `bandit -ll <file>` and fix Medium/High.
- Match the fixtures already used in the test file you are extending (read it first).

---

## File Structure

| File | Responsibility | Task |
|------|----------------|------|
| `services/app/games/opening_book_context.py` (**new**) | Walk PGN → deepest opening (id/eco/name) + leading `book_ply_count` | A |
| `services/app/games/time_control_format.py` (modify) | Add `format_time_control_label(time_class, base, inc, raw)` on top of existing `format_time_control` | A |
| `services/app/games/services_v2.py` (modify) | Add 4 derived fields + `winner_username` + winner props to `GameAnalysisDataV2`; populate them | A |
| `services/app/games/chart_data.py` (modify) | Add per-ply `book` flag to `sf_cp_payload` / `lc0_wdl_payload` | B |
| `services/app/games/views.py` (modify) | `_this_move_context` gains `is_book`/opening fields; chart partial views pass `opening_name`/`opening_id` | B |
| `services/app/templates/games/analysis.html` (modify) | Header: TC label, opening link, Open-on-chess.com + Copy-PGN buttons, winner trophy; embed PGN + copy JS | C |
| `services/app/templates/games/partials/_pgn_table.html` (modify) | `<details open>` → `<details>` (auto-collapsed) | C |
| `services/app/templates/games/partials/_move_chips.html` (modify) | "This is a book move for <Opening>" line when `is_book` | C |
| `services/app/static/games/charts/sfCp.js` (modify) | Book plies → book colour + "Book — <name>" hover | D |
| `services/app/static/games/charts/lc0Wdl.js` (modify) | Book plies → book colour on strip + hover | D |
| `services/app/static/games/charts/chartTheme.js` (modify) | Add `colors.book` | D |
| `services/app/templates/games/partials/_chart_sf_cp.html` / `_chart_lc0_wdl.html` (modify) | Expose `opening_name` to JS (data attribute / json_script) | D |

---

## Task A: Data layer — book context, TC label, dataclass fields

**Files:**
- Create: `services/app/games/opening_book_context.py`
- Test: `services/app/games/tests/test_opening_book_context.py`
- Modify: `services/app/games/time_control_format.py`
- Test: `services/app/games/tests/test_time_control_format.py` (extend)
- Modify: `services/app/games/services_v2.py`
- Test: `services/app/games/tests/test_services_v2.py` (extend)

### A1 — `book_context` helper

- [ ] **Step 1: Write the failing test** in `games/tests/test_opening_book_context.py`

```python
"""Tests for games.opening_book_context.book_context."""
from __future__ import annotations

import pytest

from games.opening_book_context import BookContext, book_context

pytestmark = pytest.mark.django_db


def test_empty_pgn_returns_no_book():
    ctx = book_context("")
    assert ctx == BookContext(opening_id=None, eco="", name="", book_ply_count=0)


def test_unparseable_pgn_returns_no_book():
    assert book_context("not a pgn").book_ply_count == 0


def test_sicilian_najdorf_resolves_deepest_and_book_plies(ingested_opening_book):
    # 1.e4 c5 2.Nf3 d6 3.d4 cxd4 4.Nxd4 Nf6 5.Nc3 a6 — Najdorf (ECO B90).
    pgn = (
        '[Event "?"]\n\n'
        "1. e4 c5 2. Nf3 d6 3. d4 cxd4 4. Nxd4 Nf6 5. Nc3 a6 6. Be3 e5 *\n"
    )
    ctx = book_context(pgn)
    assert ctx.opening_id is not None
    assert "Najdorf" in ctx.name
    # Book run is the leading contiguous matched sequence; Najdorf is reached
    # at ply 10 (a6), so every ply 1..book_ply_count is in book.
    assert ctx.book_ply_count >= 10
```

> NOTE: Read `games/tests/test_opening_resolver.py` and `test_ingest_opening.py` first to find the real fixture that ingests the opening book (named here `ingested_opening_book` — use the actual fixture name). Pick a PGN line that the test book definitely contains; mirror whatever line `test_opening_resolver.py` already exercises so you reuse known-good data.

- [ ] **Step 2: Run test, verify it fails** — `pytest games/tests/test_opening_book_context.py -v` → ImportError / FAIL.

- [ ] **Step 3: Implement** `games/opening_book_context.py`

```python
"""
Title: opening_book_context.py — Resolve a game's opening + leading book plies
Description:
    Single PGN walk that returns the deepest matched OpeningBook entry
    (id, eco, common name) plus the number of leading half-moves that are
    still "book" (opening theory). Mirrors games.opening_resolver's
    break-on-first-miss walk so the resolved opening stays consistent with
    the denormalised Game.opening FK, while also reporting the book depth
    used by the analysis charts and the "This Move" panel.

Changelog:
    2026-05-29: Initial creation (#226).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import chess.pgn

from openings.services import lookup_opening_entry


@dataclass(frozen=True)
class BookContext:
    """Resolved opening identity + leading book depth for one game.

    Attributes:
        opening_id (int | None): Deepest matched OpeningBook id, or None.
        eco (str): ECO code of the deepest match ("" when unmatched).
        name (str): Common name of the deepest match ("" when unmatched).
        book_ply_count (int): Count of leading half-moves that are book
            theory (1-indexed ply of the deepest match; 0 when unmatched).
    """

    opening_id: int | None
    eco: str
    name: str
    book_ply_count: int


_NO_BOOK = BookContext(opening_id=None, eco="", name="", book_ply_count=0)


def book_context(pgn_text: str) -> BookContext:
    """Walk a PGN and resolve the deepest opening + leading book-ply count.

    Args:
        pgn_text (str): Raw PGN. Empty/unparseable input yields a no-book result.

    Returns:
        BookContext: Deepest matched opening identity and the leading book depth.
            Walk stops at the first position with no book entry (after the start),
            matching games.opening_resolver.resolve_opening_id semantics.
    """
    if not pgn_text or not pgn_text.strip():
        return _NO_BOOK
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
    except Exception:  # noqa: BLE001 — defensive against malformed PGN
        return _NO_BOOK
    if game is None:
        return _NO_BOOK

    board = game.board()
    deepest: tuple[int, str, str] | None = lookup_opening_entry(board)
    book_ply_count = 0
    for ply, move in enumerate(game.mainline_moves(), start=1):
        board.push(move)
        hit = lookup_opening_entry(board)
        if hit is None:
            break
        deepest = hit
        book_ply_count = ply

    if deepest is None:
        return _NO_BOOK
    opening_id, eco, name = deepest
    return BookContext(
        opening_id=opening_id, eco=eco, name=name, book_ply_count=book_ply_count
    )
```

- [ ] **Step 4: Run test, verify pass** — `pytest games/tests/test_opening_book_context.py -v` → PASS. Then `bandit -ll games/opening_book_context.py`.

- [ ] **Step 5: Commit** — `git commit -m "feat(games): book_context helper resolving opening + leading book plies (#226)"`

### A2 — `format_time_control_label`

- [ ] **Step 1: Write failing test** — append to `games/tests/test_time_control_format.py` (match its existing import/style):

```python
from games.time_control_format import format_time_control_label


def test_label_prefixes_time_class_rapid():
    assert format_time_control_label("rapid", 600, 5) == "Rapid · 10+5 min"


def test_label_prefixes_time_class_daily():
    assert format_time_control_label("daily", 259200, None) == "Daily · 3 days per move"


def test_label_without_class_falls_back_to_body():
    assert format_time_control_label("", 180, 0) == "3 min"


def test_label_empty_when_unparseable_and_no_raw():
    assert format_time_control_label("blitz", None, None) == ""
```

- [ ] **Step 2: Run, verify fail** — `pytest games/tests/test_time_control_format.py -v`.

- [ ] **Step 3: Implement** — append to `games/time_control_format.py` (update the changelog header line too):

```python
def format_time_control_label(
    time_class: str | None,
    base_seconds: int | None,
    increment_seconds: int | None,
    *,
    raw: str | None = None,
) -> str:
    """Render a time control with its time-class prefix for the page header.

    Composes the existing :func:`format_time_control` body with a title-cased
    time-class prefix, e.g. ``"Rapid · 10+5 min"`` or ``"Daily · 3 days per
    move"``. When the body is empty (nothing parseable and no ``raw``) the
    result is ``""``; when the class is empty the bare body is returned.

    Args:
        time_class: Chess.com time class ("rapid", "blitz", "daily", …) or None.
        base_seconds: Per-game base time (or per-move budget for daily).
        increment_seconds: Increment in seconds; None for daily formats.
        raw: Optional original string used as a body fallback.

    Returns:
        ``"<Class> · <body>"``, the bare body, or ``""``.
    """
    body = format_time_control(base_seconds, increment_seconds, raw=raw)
    if not body:
        return ""
    cls = (time_class or "").strip()
    return f"{cls.title()} · {body}" if cls else body
```

- [ ] **Step 4: Run, verify pass** + `bandit -ll games/time_control_format.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): human-readable time-control label with class prefix (#226)"`

### A3 — `GameAnalysisDataV2` fields + population

- [ ] **Step 1: Write failing test** — append to `games/tests/test_services_v2.py` (reuse its game/analysis fixtures; read the file first). Build a game whose PGN reaches a known opening and assert:

```python
def test_v2_carries_time_control_label_and_book_fields(<existing fixtures>):
    # Arrange a game with time_class="rapid", time_control "600+5",
    # winner_username == white, and a PGN that reaches a known opening.
    data = get_game_analysis_v2(game.slug)
    assert data.time_control_label == "Rapid · 10+5 min"
    assert data.opening_book_id is not None
    assert data.opening_common_name != ""
    assert data.book_ply_count >= 2
    assert data.winner_username == game.white_username
    assert data.white_is_winner is True
    assert data.black_is_winner is False
```

> Match how `test_services_v2.py` already constructs Game + GameAnalysis rows. Ensure the opening book is ingested (same fixture as A1).

- [ ] **Step 2: Run, verify fail**.

- [ ] **Step 3: Implement** in `services/app/games/services_v2.py`:

(a) Add imports at top:
```python
from games.opening_book_context import book_context
from games.time_control_format import format_time_control_label
from games.time_control_parser import parse_time_control
```

(b) Add fields to `GameAnalysisDataV2` (after `opening_id`):
```python
    time_control_label: str = ""
    opening_book_id: int | None = None
    opening_common_name: str = ""
    book_ply_count: int = 0
    winner_username: str | None = None
```

(c) Add winner properties to the dataclass (next to `white_label`):
```python
    @property
    def white_is_winner(self) -> bool:
        """True when the White player is the recorded game winner."""
        wu = (self.winner_username or "").lower()
        return bool(wu) and wu == (self.white or "").lower()

    @property
    def black_is_winner(self) -> bool:
        """True when the Black player is the recorded game winner."""
        wu = (self.winner_username or "").lower()
        return bool(wu) and wu == (self.black or "").lower()
```

(d) In `_build_dataclass_kwargs`, compute and add the derived values. Replace the
return dict's tail so it also sets the new keys:
```python
    base_s = db_game.time_control_base_s
    inc_s = db_game.time_control_increment_s
    if base_s is None:
        base_s, inc_s = parse_time_control(db_game.time_control or "")
    raw_tc = db_game.time_control or pgn_game.headers.get("TimeControl", "")
    tc_label = format_time_control_label(
        db_game.time_class, base_s, inc_s, raw=raw_tc
    )
    book = book_context(pgn_text)
```
then in the returned dict add:
```python
        "time_control_label": tc_label,
        "opening_book_id": db_game.opening_id or book.opening_id,
        "opening_common_name": book.name,
        "book_ply_count": book.book_ply_count,
        "winner_username": db_game.winner_username,
```

> `db_game.opening_id` is the denormalised FK column (authoritative when set);
> `book.opening_id` is the fallback from the live walk. `book.name` is the
> common name (OpeningBook.name) for both the header label and the chart/panel.

- [ ] **Step 4: Run** `pytest games/tests/test_services_v2.py -v` → PASS, then re-run the A1/A2 tests and `bandit -ll games/services_v2.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): GameAnalysisDataV2 carries TC label, book context, winner (#226)"`

---

## Task B: Payloads — per-ply book flag + opening on chart context

**Depends on:** Task A (uses `data.book_ply_count`, `data.opening_book_id`, `data.opening_common_name`).

**Files:**
- Modify: `services/app/games/chart_data.py`
- Test: `services/app/games/tests/test_chart_data.py` (extend)
- Modify: `services/app/games/views.py` (`_this_move_context`, `chart_sf_cp_partial`, `chart_lc0_wdl_partial`)
- Test: `services/app/games/tests/test_chip_data.py` and/or `test_partial_routes.py` (extend)

### B1 — `book` flag in chart payloads

- [ ] **Step 1: Failing test** — append to `test_chart_data.py` (reuse its data fixture; set `data.book_ply_count = 4`):

```python
def test_sf_cp_payload_marks_leading_book_plies(<fixture building data>):
    data.book_ply_count = 4
    rows = sf_cp_payload(data)
    assert all(r["book"] is True for r in rows if r["ply"] <= 4)
    assert all(r["book"] is False for r in rows if r["ply"] > 4)


def test_lc0_wdl_payload_marks_leading_book_plies(<fixture building data>):
    data.book_ply_count = 2
    rows = lc0_wdl_payload(data)
    assert all(r["book"] == (r["ply"] <= 2) for r in rows)
```

- [ ] **Step 2: Run, verify fail**.
- [ ] **Step 3: Implement** — in `chart_data.py` add `"book": m.ply <= data.book_ply_count,` to each dict in both `sf_cp_payload` and `lc0_wdl_payload`. Update the module changelog header.
- [ ] **Step 4: Run, verify pass** + `bandit -ll games/chart_data.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): per-ply book flag in SF/LC0 chart payloads (#226)"`

### B2 — `is_book` + opening in "This Move" context; opening name on chart partials

- [ ] **Step 1: Failing test** — extend `test_chip_data.py` (or wherever `_this_move_context` is covered; if it's view-level, use `test_partial_routes.py`). Assert the chips partial context for a book ply contains `is_book=True`, `opening_common_name`, `opening_id`; and for a post-book ply `is_book=False`. Also assert `chart_sf_cp_partial` / `chart_lc0_wdl_partial` responses pass `opening_name` (render-level: the rendered HTML contains the opening name in the chart partial's data attribute — see Task D for the attribute). Match existing test patterns in `test_partial_routes.py`.

- [ ] **Step 2: Run, verify fail**.
- [ ] **Step 3: Implement** in `views.py`:

(a) In `_this_move_context(data, ply)`, in BOTH the `ply <= 0` early dict and the normal return dict, add:
```python
        "is_book": 0 < ply <= data.book_ply_count,
        "opening_common_name": data.opening_common_name,
        "opening_id": data.opening_book_id,
```
(for the `ply <= 0` branch `is_book` is `False`).

(b) In `chart_sf_cp_partial` add to the render context:
```python
        "opening_name": data.opening_common_name,
        "opening_id": data.opening_book_id,
```
(c) In `chart_lc0_wdl_partial` add the same two keys.

- [ ] **Step 4: Run, verify pass** + `bandit -ll games/views.py`.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): book flag + opening in This Move and chart contexts (#226)"`

---

## Task C: Header, auto-collapse PGN, This-Move book line (templates)

**Depends on:** Task A (header fields), Task B (chips `is_book`/opening).

**Files:**
- Modify: `services/app/templates/games/analysis.html`
- Modify: `services/app/templates/games/partials/_pgn_table.html`
- Modify: `services/app/templates/games/partials/_move_chips.html`
- Test: `services/app/games/tests/test_view_game_analysis_shell.py` and `test_partial_routes.py` (extend)

> Django template reminder: `{# #}`, `{% %}` and `{{ }}` are **single-line only** — never break a tag across lines.

### C1 — Header (`analysis.html` page-hero)

- [ ] **Step 1: Failing test** — extend `test_view_game_analysis_shell.py`: render `game_analysis` for a game with a chess.com `Link` header, a known opening, `time_class`/time control set, and a winner; assert the response contains: the TC label text (e.g. `"Rapid · "`), the opening common name, an `href` to `/openings/<id>/`, `Open on Chess.com`, `Copy PGN`, and the trophy `🏆`.

- [ ] **Step 2: Run, verify fail**.
- [ ] **Step 3: Implement** — replace the `page-hero` block (lines ~155-161) with:

```html
<div class="page-hero">
  <div>
    <h1>{% if no_data %}{{ game.white_username }} vs {{ game.black_username }}{% else %}{% if data.white_is_winner %}<span class="winner-trophy" title="Winner" aria-label="Winner">🏆</span> {% endif %}{{ data.white_label }} vs {% if data.black_is_winner %}<span class="winner-trophy" title="Winner" aria-label="Winner">🏆</span> {% endif %}{{ data.black_label }}{% endif %}</h1>
    {% if not no_data %}<p class="page-hero-sub">{{ data.result }} · {{ data.date }} · {{ data.time_control_label }}{% if data.opening_book_id %} · <a href="{% url 'openings:detail' data.opening_book_id %}" class="page-hero-opening">{{ data.opening_common_name }}</a>{% endif %}</p>{% endif %}
  </div>
  <div class="flex gap-2 flex-wrap">
    {% if not no_data and data.url %}<a href="{{ data.url }}" target="_blank" rel="noopener noreferrer" class="wc-btn wc-btn-ghost">Open on Chess.com ↗</a>{% endif %}
    {% if not no_data and data.pgn %}<button type="button" id="copy-pgn-btn" class="wc-btn wc-btn-ghost" data-copy-label="Copy PGN" data-copied-label="Copied!">Copy PGN</button>{% endif %}
    <a href="{% url 'dashboard:index' %}" class="wc-btn wc-btn-ghost">← Dashboard</a>
  </div>
</div>
```

- [ ] **Step 3b:** Add the PGN payload + copy script. In `analysis.html` inside `{% block content %}` (just after the hero, still under `{% if not no_data %}`), embed the PGN:
```html
{{ data.pgn|json_script:"game-pgn-data" }}
```
and in `{% block extra_js %}` (inside the existing `{% if not no_data %}`), add a script:
```html
<script>
(function () {
  var btn = document.getElementById("copy-pgn-btn");
  var raw = document.getElementById("game-pgn-data");
  if (!btn || !raw) return;
  var pgn = JSON.parse(raw.textContent || '""');
  btn.addEventListener("click", function () {
    function done() {
      var orig = btn.getAttribute("data-copy-label");
      btn.textContent = btn.getAttribute("data-copied-label");
      setTimeout(function () { btn.textContent = orig; }, 1600);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(pgn).then(done).catch(function () {});
    } else {
      var ta = document.createElement("textarea");
      ta.value = pgn; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } finally { document.body.removeChild(ta); }
    }
  });
})();
</script>
```

- [ ] **Step 3c:** Add header/trophy CSS to the existing `<style>` block in `analysis.html`:
```css
.winner-trophy { font-size: 0.85em; }
.page-hero-opening { color: var(--color-gold); text-decoration: underline; text-underline-offset: 2px; }
.page-hero-opening:hover { color: var(--color-rust); }
```

- [ ] **Step 4: Run** `pytest games/tests/test_view_game_analysis_shell.py -v` → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): informative analysis header — TC, opening link, chess.com + copy-PGN, trophy (#226)"`

### C2 — Auto-collapse Moves PGN

- [ ] **Step 1: Failing test** — in `test_partial_routes.py` assert the pgn partial response does **not** contain `<details open` (it should be a plain `<details`). Add:
```python
def test_pgn_partial_starts_collapsed(<existing fixture>):
    resp = client.get(f"/_partials/games/{slug}/pgn/")
    assert b"<details open" not in resp.content
    assert b'id="pgn-panel"' in resp.content
```
- [ ] **Step 2: Run, verify fail**.
- [ ] **Step 3: Implement** — in `_pgn_table.html` change `<details open id="pgn-panel" class="moves-panel">` to `<details id="pgn-panel" class="moves-panel">`. Add a changelog line.
- [ ] **Step 4: Run, verify pass**.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): Moves PGN block starts collapsed (#226)"`

### C3 — "This Move" book line

- [ ] **Step 1: Failing test** — in `test_partial_routes.py` assert the chips partial for a book ply contains "book move" text and an `/openings/<id>/` link; a non-book ply does not.
- [ ] **Step 2: Run, verify fail**.
- [ ] **Step 3: Implement** — in `_move_chips.html`, inside `<div class="this-move__main">` after the `this-move__ident` paragraph, add:
```html
{% if is_book and opening_id %}<p class="this-move__book">This is a book move for <a href="{% url 'openings:detail' opening_id %}">{{ opening_common_name }}</a>.</p>{% endif %}
```
And add CSS to `analysis.html` `<style>`:
```css
.this-move__book { font-size: 0.72rem; color: var(--color-peat); margin: 2px 0 6px; font-family: var(--font-mono); }
.this-move__book a { color: var(--color-gold); }
```
- [ ] **Step 4: Run, verify pass**.
- [ ] **Step 5: Commit** — `git commit -m "feat(games): This Move panel flags book moves with opening link (#226)"`

---

## Task D: Chart book styling (JS/CSS) + Tailwind rebuild

**Depends on:** Task B (payload `book` flag + partial `opening_name`).

**Files:**
- Modify: `services/app/static/games/charts/chartTheme.js`
- Modify: `services/app/static/games/charts/sfCp.js`
- Modify: `services/app/static/games/charts/lc0Wdl.js`
- Modify: `services/app/templates/games/partials/_chart_sf_cp.html`, `_chart_lc0_wdl.html`

> JS has no unit harness here — verify by rendering the page (Task E). Read each JS file fully before editing; preserve the existing perspective-flip / ply-sync logic.

- [ ] **Step 1: Theme colour** — in `chartTheme.js` add a `book` entry to the `colors` object: a muted, judgment-neutral slate so book moves read as "theory, not graded": `book: "#7C8AA0"` (align to the nearest existing palette token if one fits).

- [ ] **Step 2: Expose opening name to JS** — in `_chart_sf_cp.html`, add `data-opening-name="{{ opening_name|default:'' }}"` to the `#sf-cp-chart` div. In `_chart_lc0_wdl.html`, add `data-opening-name="{{ opening_name|default:'' }}"` to the `#lc0-wdl-chart` div.

- [ ] **Step 3: sfCp.js book styling** —
  - In the `rawPoints` map, carry `book: !!d.book` onto each point (and through `getPointsForPerspective`'s two `.map` rebuilds — add `book: p.book`).
  - Read the opening name once near the top: `var openingName = div.getAttribute("data-opening-name") || "";`
  - In `buildTraces`, when `p.book` is true, force the bar colour to `theme.colors.book` (book overrides classification colour, even for own-side plies). In `buildShapes`, skip the classification endcap when `p.book` (a book move has no quality grade).
  - Per-point hover: switch to a per-point hovertext for book plies. Simplest: build a `hovertext` array and set `hovertemplate` to use `%{text}` where book points get `"Book — " + openingName` (fallback `"Book move"` when name empty) and non-book keep the existing `player played san (±x pawns)` string. Implement by computing a `text` array parallel to `customdata` and a single `hovertemplate: "%{text}<extra></extra>"`.

- [ ] **Step 4: lc0Wdl.js book styling** — read `lc0Wdl.js` fully. The per-ply classification strip beneath the chart is where move-quality is shown; for book plies render the strip cell with `theme.colors.book` and a `title`/tooltip of `"Book — " + openingName`. If the WDL chart hover also names move quality, append the book note there too. Carry `book` from the payload through the strip-building code.

- [ ] **Step 5: Verify rendering** — see Task E (run the app, click through early plies, confirm book bars/strip cells are slate and hover shows the opening; confirm post-book plies are unchanged).

- [ ] **Step 6: Commit** — `git commit -m "feat(games): book-move styling + opening hover on SF/LC0 charts (#226)"`

- [ ] **Step 7: Tailwind rebuild (LAST css step)** — only if any new Tailwind utility classes were introduced in templates (the plan uses existing `wc-btn`/`flex`/`gap-2` utilities, which already exist — but rebuild anyway to be safe since Tailwind v4 content-scans `templates/**`). Run with Node 22 to avoid byte-diff CI failures:
```bash
cd services/app && npx node@22 ./bin/build_tailwind.sh    # or: bash bin/build_tailwind.sh under a Node 22 shell
git add services/app/static/**/tailwind.css && git commit -m "chore(games): rebuild tailwind for #226 header/book styles"
```
> Verify the build script's exact invocation in `services/app/bin/build_tailwind.sh`. `tailwind.css` is a committed artifact — never hand-edit. If `git diff` shows no change, skip the commit.

---

## Task E: Verification & finish

- [ ] **Step 1: Full games test suite** — `cd services/app && source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate && pytest games/ -q`. All green.
- [ ] **Step 2: Bandit on all edited Python** — `bandit -ll games/opening_book_context.py games/time_control_format.py games/services_v2.py games/chart_data.py games/views.py`. No Medium/High.
- [ ] **Step 3: Manual run** (use the `run` / `verify` skill): launch the app with `DEBUG=True AUTH_ENABLED=True` from the worktree (symlink `.env` as needed — classifier blocks the agent, so the user provides it). Open a game detail page and confirm every acceptance-criteria item renders: friendly TC, opening link, both header buttons (copy works), winner trophy, book bars on both charts + book hover, "book move" line in This Move for early plies, Moves PGN collapsed by default.
- [ ] **Step 4: Quality gate** — confirm the per-edit hook is green across the branch; run the repo quality pipeline if available.
- [ ] **Step 5: Finish** — use superpowers:finishing-a-development-branch to open the PR against `main` referencing #226. (No merge to main without explicit per-PR consent.)

---

## Self-Review (spec coverage)

| Acceptance criterion | Task |
|---|---|
| Human-readable time control | A2 (`format_time_control_label`) + A3 + C1 |
| Opening in header by common name + link | A1/A3 (`opening_common_name`/`opening_book_id`) + C1 |
| Open on Chess.com button | C1 (uses `data.url`) |
| Copy PGN button (clipboard) | C1 (json_script + copy JS) |
| Winner trophy in H1 | A3 (`winner_username`/`white_is_winner`/`black_is_winner`) + C1 |
| Identify leading book sequence | A1 (`book_ply_count`) |
| Book style on SF + LC0 charts | B1 (`book` flag) + D (sfCp.js/lc0Wdl.js) |
| Chart hover shows book + opening | D (hovertext + `data-opening-name`) — link lives in header/panel per decision #3 |
| "This Move" shows book-move line + link | B2 (`is_book`/opening) + C3 |
| Moves PGN auto-collapsed | C2 |

No DB migration required (all derived). No new third-party deps.
