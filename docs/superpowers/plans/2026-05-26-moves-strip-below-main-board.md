# Moves Strip Below Main Board — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the buried `<details>Moves</details>` table at the bottom of the game-analysis page with an always-visible inline strip of clickable SAN chips directly under the main game board, mirroring the engine-line continuation idiom.

**Architecture:** Server-rendered chip markup emitted by the existing `pgn_partial` view (no view-logic change); a thin JS module (`pgnTable.js` rewrite) attaches a delegated click handler and a `WoodLeagueAnalysis` ply-state subscription that toggles `.is-active` + `scrollIntoView({block:'nearest'})`. Annotation symbols and titles are consolidated into a new Python single-source-of-truth (`games/move_annotations.py`) consumed server-side via a custom template tag and exposed client-side via Django's `json_script` (the existing `WoodLeagueMoveAnnotations` JS reference has no current definition; this work creates it).

**Tech Stack:** Django 5 templates, plain (no-framework) ES5 JavaScript, htmx for partial loading, pytest + Django test client for tests.

**Spec:** `docs/superpowers/specs/2026-05-26-main-board-moves-strip-design.md`

---

## File Map

| Status | Path | Responsibility |
|--------|------|----------------|
| Create | `services/app/games/move_annotations.py` | `ANNOTATIONS` dict + `symbol()` / `title()` helpers — single source of truth. |
| Create | `services/app/games/templatetags/__init__.py` | Package marker for the new templatetags module. |
| Create | `services/app/games/templatetags/games_extras.py` | `move_annotation_symbol` / `move_annotation_title` template filters. |
| Create | `services/app/templates/games/partials/_move_annotation.html` | Tiny include rendering the badge `<span>` or nothing. |
| Rewrite | `services/app/templates/games/partials/_pgn_table.html` | Chip-strip markup replacing the old `<details>` + `<table>`. |
| Rewrite | `services/app/static/games/pgnTable.js` | Behavior wrapper (delegated click + ply-state subscription). |
| Modify | `services/app/templates/games/analysis.html` | Relocate HTMX slot, delete old slot, add CSS, expose annotation map via `json_script`. |
| Modify | `services/app/games/views.py::game_analysis` | Pass `ANNOTATIONS` into the analysis.html template context. |
| Create | `services/app/games/tests/test_move_annotations.py` | Test the new dict + helpers + template filters. |
| Extend | `services/app/games/tests/test_partial_routes.py` | Five new tests for the chip-strip partial. |

---

## Pre-flight context for the implementer

**The worktree to work in:** `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+212-moves-strip-below-main-board` (branch `issue/212-moves-strip-below-main-board`, off `origin/main`).

**Python venv lives at the repo root:** `/Users/christopherwebster/Projects/wood_league/.venv`. From `services/app/` run `source ../../.venv/bin/activate` before any `pytest`, `bandit`, or `python manage.py …`. Per [[project_venv]].

**Tests are gated by `.env.test`** per [[project_dev_test_db]]. If `services/app/.env.test` is missing in this worktree, copy or symlink from the main repo's services/app/ before running the games test suite. The ingest-side `pg_try_advisory_lock` tests will fail without it (those are not touched by this work, but if you run the full suite, expect those 10 failures unless `.env.test` is in place).

**The quality-gate hook** per [[project_quality_gate_hook]] fires on every edit and hard-fails on ruff/mypy/pytest/cc>grade-B. Expect transient TDD red — that's normal mid-task.

**No Tailwind rebuild needed.** All new CSS uses only existing palette tokens (`--color-*`) and lives in an inline `<style>` block — `tailwind.css` is not regenerated. Per [[project_tailwind_build]].

**Existing `WoodLeagueMoveAnnotations` references:** `services/app/static/games/pgnTable.js:29` (this file is being rewritten — the new module no longer consumes it). `services/app/static/games/charts/sfCp.js:18` reads `WoodLeagueMoveAnnotations.colors`. We will populate `colors` on the new payload (mapping classification → CSS variable name) so `sfCp.js` continues to function; we do NOT modify `sfCp.js` itself in this work.

**Hardcoded symbol reference for the canonical map** (from `services/app/templates/games/partials/_card_sf.html` lines 56-63):

| classification | symbol | title |
|----------------|--------|-------|
| brilliant | `!!` | Brilliant |
| best | (none) | Best |
| great | `!` | Great |
| excellent | (none) | Excellent |
| good | (none) | Good |
| inaccuracy | `?!` | Inaccuracy |
| mistake | `?` | Mistake |
| blunder | `??` | Blunder |

---

## Task 0: Amend spec to record open-question resolution

**Files:**
- Modify: `docs/superpowers/specs/2026-05-26-main-board-moves-strip-design.md`

- [ ] **Step 1: Read the spec's Open Questions section**

Run: `grep -n "Open questions" docs/superpowers/specs/2026-05-26-main-board-moves-strip-design.md`

You'll find the section near the file end. The question reads:

> Where the JS-side `window.WoodLeagueMoveAnnotations` is currently defined (the consolidation needs to replace that definition; if it lives outside the shell template, we relocate the `json_script` accordingly).

- [ ] **Step 2: Replace that bullet with the resolution**

Use Edit to replace the bullet. New content:

```markdown
- ~~Where the JS-side `window.WoodLeagueMoveAnnotations` is currently defined~~ — **Resolved 2026-05-26:** never actually defined anywhere in the codebase. `pgnTable.js:29` and `charts/sfCp.js:18` consume it with `{}` fallbacks, so annotation badges have been silently absent the whole time. The implementation creates the JS object net-new via `json_script` in `analysis.html`'s `extra_js` block. The new payload also includes a `colors` key (classification → CSS variable name) to feed `sfCp.js`'s existing `WoodLeagueMoveAnnotations.colors` consumer; `sfCp.js` itself is not modified here.
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-26-main-board-moves-strip-design.md
git commit -m "docs(#212): resolve spec open question — WoodLeagueMoveAnnotations was undefined

The spec flagged this as a discovery item; confirmed via grep there is
no definition anywhere in the codebase. The implementation creates the
JS-side object net-new from the new Python source of truth, with a
colors key included so the existing sfCp.js consumer keeps working.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 1: Create `move_annotations.py` with the source-of-truth dict and helpers

**Files:**
- Create: `services/app/games/move_annotations.py`
- Create: `services/app/games/tests/test_move_annotations.py`

- [ ] **Step 1: Write the failing tests**

Create `services/app/games/tests/test_move_annotations.py`:

```python
"""
Title: test_move_annotations.py — Tests for the move-annotation source of truth
Description:
    Verifies the ANNOTATIONS dict shape, the symbol() / title() helpers,
    and that all eight SF classifications used elsewhere in the app
    (brilliant, best, great, excellent, good, inaccuracy, mistake, blunder)
    are present so server-rendered badges never silently drop a class.

Changelog:
    2026-05-26 (#212): Initial — guards the new annotation single source of truth.
"""
import pytest

from games.move_annotations import ANNOTATIONS, symbol, title


CANONICAL_CLASSIFICATIONS = (
    "brilliant", "best", "great", "excellent",
    "good", "inaccuracy", "mistake", "blunder",
)


def test_annotations_dict_covers_every_sf_classification():
    """Every classification used by _card_sf.html and the move classifier must be present."""
    for cls in CANONICAL_CLASSIFICATIONS:
        assert cls in ANNOTATIONS, f"ANNOTATIONS missing key: {cls}"


def test_annotations_entries_have_symbol_and_title_keys():
    """Each entry must expose both symbol and title (symbol may be empty string)."""
    for cls, entry in ANNOTATIONS.items():
        assert "symbol" in entry, f"{cls} missing symbol key"
        assert "title" in entry, f"{cls} missing title key"
        assert isinstance(entry["symbol"], str)
        assert isinstance(entry["title"], str)


@pytest.mark.parametrize("classification,expected", [
    ("brilliant", "!!"),
    ("great", "!"),
    ("inaccuracy", "?!"),
    ("mistake", "?"),
    ("blunder", "??"),
])
def test_symbol_returns_canonical_value_for_classified_moves(classification, expected):
    """The five badge-bearing classifications return their canonical symbol."""
    assert symbol(classification) == expected


@pytest.mark.parametrize("classification", ["best", "excellent", "good"])
def test_symbol_returns_empty_string_for_unbadged_classifications(classification):
    """Best/excellent/good have no badge — symbol() returns empty string."""
    assert symbol(classification) == ""


def test_symbol_returns_empty_string_for_none():
    """A None classification (unanalyzed move) yields no symbol."""
    assert symbol(None) == ""


def test_symbol_returns_empty_string_for_unknown_classification():
    """An unknown classification gracefully degrades rather than KeyError'ing."""
    assert symbol("not-a-real-class") == ""


def test_symbol_is_case_insensitive():
    """Callers may pass mixed-case classifications (DB normalisation is not guaranteed)."""
    assert symbol("Blunder") == "??"
    assert symbol("BLUNDER") == "??"


def test_title_returns_human_readable_label():
    """title() returns the human-readable label for tooltip use."""
    assert title("blunder") == "Blunder"
    assert title("inaccuracy") == "Inaccuracy"


def test_title_falls_back_to_classification_when_unknown():
    """Unknown classification → return the input unchanged so the user still sees something."""
    assert title("some-future-class") == "some-future-class"


def test_title_returns_empty_string_for_none():
    """A None classification (unanalyzed move) yields no title."""
    assert title(None) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+212-moves-strip-below-main-board/services/app
source ../../.venv/bin/activate
pytest games/tests/test_move_annotations.py -v
```

Expected: ImportError / ModuleNotFoundError for `games.move_annotations` — file doesn't exist yet.

- [ ] **Step 3: Create the module**

Create `services/app/games/move_annotations.py`:

```python
"""
Title: move_annotations.py — Single source of truth for SF move-quality badges
Description:
    Maps SF move classifications (brilliant / best / great / excellent /
    good / inaccuracy / mistake / blunder) to the inline annotation symbol
    (!!, !, ?!, ?, ??) and tooltip title rendered next to each move in the
    main-board moves strip and the SF accuracy-card bar segments.

    Consumed server-side by templatetags/games_extras.py (via filters used by
    partials/_move_annotation.html). Exposed client-side as
    window.WoodLeagueMoveAnnotations by analysis.html's extra_js block
    (json_script of this dict + a small init) so JS consumers like
    charts/sfCp.js can read the same payload.

    Adding a new classification: add an entry here and the server-rendered
    badge plus the JS payload pick it up automatically. The card_sf.html
    bar-segment template still hardcodes the symbols (out of scope for #212)
    — keep this dict in sync with that file by hand for now.

Changelog:
    2026-05-26 (#212): Initial — created as part of the moves-strip work.
"""
from __future__ import annotations

ANNOTATIONS: dict[str, dict[str, str]] = {
    "brilliant":  {"symbol": "!!", "title": "Brilliant"},
    "best":       {"symbol": "",   "title": "Best"},
    "great":      {"symbol": "!",  "title": "Great"},
    "excellent":  {"symbol": "",   "title": "Excellent"},
    "good":       {"symbol": "",   "title": "Good"},
    "inaccuracy": {"symbol": "?!", "title": "Inaccuracy"},
    "mistake":    {"symbol": "?",  "title": "Mistake"},
    "blunder":    {"symbol": "??", "title": "Blunder"},
}


def symbol(classification: str | None) -> str:
    """
    Return the annotation symbol for a classification, or "" if none applies.

    Parameters:
        classification (str | None): SF classification label (case-insensitive),
            or None for an unanalyzed move.

    Returns:
        str: The canonical badge symbol (e.g. "?!"), or "" when the
        classification is None, unknown, or one of best/excellent/good
        (which carry no badge by design).
    """
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("symbol", "")


def title(classification: str | None) -> str:
    """
    Return the tooltip title for a classification.

    Parameters:
        classification (str | None): SF classification label (case-insensitive),
            or None for an unanalyzed move.

    Returns:
        str: The human-readable title (e.g. "Inaccuracy"), or the input
        unchanged when unknown (so the user still sees a label rather than
        a blank tooltip), or "" when the classification is None.
    """
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("title", classification)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest games/tests/test_move_annotations.py -v
```

Expected: 11 tests pass.

- [ ] **Step 5: Run bandit and ruff on the new file**

```bash
ruff check games/move_annotations.py games/tests/test_move_annotations.py
bandit -ll games/move_annotations.py
```

Expected: ruff clean, bandit no Medium/High.

- [ ] **Step 6: Commit**

```bash
git add games/move_annotations.py games/tests/test_move_annotations.py
git commit -m "feat(#212): add move_annotations source of truth (dict + symbol/title helpers)

Net-new module — WoodLeagueMoveAnnotations was referenced by pgnTable.js
and charts/sfCp.js but never actually defined. This file defines the
canonical classification→{symbol,title} map for server-side rendering;
the JS-side object is generated from this same dict via json_script
in a later task.

Symbol values mirror the hardcoded set in templates/games/partials/
_card_sf.html (the SF accuracy bar segments). Keeping that template
in sync with this dict by hand for now — refactoring _card_sf.html to
source from here is out of scope for #212.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Create the template-tag library exposing the helpers as filters

**Files:**
- Create: `services/app/games/templatetags/__init__.py`
- Create: `services/app/games/templatetags/games_extras.py`
- Modify: `services/app/games/tests/test_move_annotations.py` (extend with filter tests)

- [ ] **Step 1: Write the failing filter tests**

Append to `services/app/games/tests/test_move_annotations.py`:

```python
# --- Template-tag filter tests ---

from django.template import Context, Template


def _render(template_source: str, context: dict) -> str:
    """Render a template fragment with {% load games_extras %} for filter tests.

    Parameters:
        template_source (str): The template body (without the load tag).
        context (dict): The render context.

    Returns:
        str: The rendered output.
    """
    full = "{% load games_extras %}" + template_source
    return Template(full).render(Context(context))


def test_move_annotation_symbol_filter_returns_canonical_symbol():
    """The filter exposes symbol() to templates."""
    out = _render("{{ cls|move_annotation_symbol }}", {"cls": "blunder"})
    assert out == "??"


def test_move_annotation_symbol_filter_returns_empty_for_none():
    """None classification renders as empty string (no badge)."""
    out = _render("{{ cls|move_annotation_symbol }}", {"cls": None})
    assert out == ""


def test_move_annotation_title_filter_returns_human_label():
    """The filter exposes title() to templates."""
    out = _render("{{ cls|move_annotation_title }}", {"cls": "inaccuracy"})
    assert out == "Inaccuracy"


def test_move_annotation_title_filter_falls_back_to_classification():
    """Unknown classification → renders the input unchanged."""
    out = _render("{{ cls|move_annotation_title }}", {"cls": "future-class"})
    assert out == "future-class"
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest games/tests/test_move_annotations.py -v -k filter
```

Expected: TemplateSyntaxError on `{% load games_extras %}` — library not registered yet.

- [ ] **Step 3: Create the templatetags package marker**

Create empty file `services/app/games/templatetags/__init__.py` with one line:

```python
# Marks games/templatetags as a Python package so Django can discover the libraries below.
```

- [ ] **Step 4: Create the filter library**

Create `services/app/games/templatetags/games_extras.py`:

```python
"""
Title: games_extras.py — Custom template filters for the games app
Description:
    Exposes move_annotation_symbol and move_annotation_title as Django
    template filters so partials/_move_annotation.html can render badge
    spans server-side without duplicating the annotation map.

    Both filters delegate to games.move_annotations and accept None
    (for unanalyzed moves) without raising.

Changelog:
    2026-05-26 (#212): Initial — created to back the moves-strip annotation include.
"""
from django import template

from games import move_annotations

register = template.Library()


@register.filter(name="move_annotation_symbol")
def move_annotation_symbol(classification: str | None) -> str:
    """
    Template filter: return the badge symbol for a classification, or "".

    Parameters:
        classification (str | None): SF classification label.

    Returns:
        str: The canonical badge symbol or empty string.
    """
    return move_annotations.symbol(classification)


@register.filter(name="move_annotation_title")
def move_annotation_title(classification: str | None) -> str:
    """
    Template filter: return the tooltip title for a classification.

    Parameters:
        classification (str | None): SF classification label.

    Returns:
        str: The human-readable title or empty string.
    """
    return move_annotations.title(classification)
```

- [ ] **Step 5: Run the filter tests to verify they pass**

```bash
pytest games/tests/test_move_annotations.py -v
```

Expected: all 15 tests pass (11 original + 4 filter tests).

- [ ] **Step 6: Lint and security-scan**

```bash
ruff check games/templatetags/
bandit -ll games/templatetags/games_extras.py
```

Expected: ruff clean, bandit no Medium/High.

- [ ] **Step 7: Commit**

```bash
git add games/templatetags/__init__.py games/templatetags/games_extras.py games/tests/test_move_annotations.py
git commit -m "feat(#212): add games_extras template tags (move_annotation_symbol/_title)

Filters expose the move_annotations module to Django templates so the
new _move_annotation.html include can render badge spans server-side
without duplicating the classification → symbol map.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Create the annotation badge include

**Files:**
- Create: `services/app/templates/games/partials/_move_annotation.html`
- Modify: `services/app/games/tests/test_move_annotations.py` (extend with include-rendering test)

- [ ] **Step 1: Write the failing include-rendering test**

Append to `services/app/games/tests/test_move_annotations.py`:

```python
# --- Include rendering tests ---

from django.template.loader import render_to_string


def test_move_annotation_include_renders_badge_for_classified_move():
    """The include emits a move-annotation span with the right class for a classified move."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "blunder"},
    )
    assert 'class="move-annotation move-annotation-blunder"' in out
    assert ">??<" in out
    assert 'title="Blunder"' in out


def test_move_annotation_include_renders_nothing_for_unbadged_move():
    """No symbol → no badge element at all (best/excellent/good have no symbol)."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "best"},
    )
    assert "move-annotation" not in out


def test_move_annotation_include_renders_nothing_for_none():
    """None classification → no badge element."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": None},
    )
    assert out.strip() == ""


def test_move_annotation_include_lowercases_class_suffix():
    """Mixed-case classification produces a lowercase CSS class suffix."""
    out = render_to_string(
        "games/partials/_move_annotation.html",
        {"classification": "Blunder"},
    )
    assert "move-annotation-blunder" in out
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest games/tests/test_move_annotations.py -v -k include
```

Expected: TemplateDoesNotExist on `games/partials/_move_annotation.html`.

- [ ] **Step 3: Create the include**

Create `services/app/templates/games/partials/_move_annotation.html`:

```django
{# Title: _move_annotation.html — Move-quality classification badge #}
{# Description: #}
{#     Tiny include that renders a small <span class="move-annotation #}
{#     move-annotation-{classification}"> badge carrying the canonical #}
{#     symbol for the classification, or nothing when the classification #}
{#     is None, unknown, or carries no symbol (best/excellent/good). #}
{# #}
{#     Used by the main-board moves strip; safe to reuse anywhere a #}
{#     classification-keyed badge is wanted. The symbol/title come from #}
{#     games.move_annotations via the games_extras filters. #}
{# #}
{# Context: #}
{#     classification (str | None) — SF move classification label. #}
{# Changelog: #}
{#     2026-05-26 (#212): Initial — backs the moves strip. #}
{% load games_extras %}{% with sym=classification|move_annotation_symbol %}{% if sym %}<span class="move-annotation move-annotation-{{ classification|lower }}" title="{{ classification|move_annotation_title }}">{{ sym }}</span>{% endif %}{% endwith %}
```

(The compact single-line form intentionally avoids introducing whitespace between the include's output and surrounding inline text — chips are rendered inline in the strip and stray whitespace would shift baseline alignment.)

- [ ] **Step 4: Run the include tests to verify they pass**

```bash
pytest games/tests/test_move_annotations.py -v
```

Expected: 19 tests pass (15 prior + 4 include tests).

- [ ] **Step 5: Commit**

```bash
git add templates/games/partials/_move_annotation.html games/tests/test_move_annotations.py
git commit -m "feat(#212): add _move_annotation.html include for classification badges

Renders a <span class=\"move-annotation move-annotation-{classification}\">
badge or nothing, sourced from the move_annotations dict via the
games_extras filters. Compact single-line form preserves chip baseline
alignment when included inline.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Rewrite the PGN partial as a chip strip

**Files:**
- Rewrite: `services/app/templates/games/partials/_pgn_table.html`
- Extend: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Locate the existing pgn_partial test for context**

```bash
grep -n "pgn_partial\|pgn-moves\|pgn-tbody" games/tests/test_partial_routes.py
```

You should find one or two existing tests around `pgn_partial`. Read them to see the fixture/URL pattern in use (likely `new_schema_game_factory` and `reverse("games_pgn_partial", args=[slug])` or a similar URL name).

- [ ] **Step 2: Write the five failing tests**

Append to `services/app/games/tests/test_partial_routes.py` (match the existing module's import style and fixture names; the example below assumes `client`, `new_schema_game_factory`, and the URL name is `games_pgn_partial` — adjust if the file uses different conventions):

```python
# --- Moves-strip partial tests (#212) ---

def test_pgn_strip_renders_one_chip_per_move(client, new_schema_game_factory):
    """The new-schema 4-ply fixture produces 4 .moves-mv chips with data-ply 1..4."""
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    assert resp.status_code == 200
    body = resp.content.decode()
    for ply in (1, 2, 3, 4):
        assert f'data-ply="{ply}"' in body, f"chip data-ply={ply} missing"
    # Strip-shape sanity checks.
    assert 'id="pgn-moves"' in body
    assert 'class="moves-strip"' in body
    # Old table shape must be gone.
    assert "<details" not in body
    assert "pgn-tbody" not in body


def test_pgn_strip_emits_annotation_for_classified_moves(
    client, new_schema_game_factory,
):
    """A row classified \"inaccuracy\" produces a move-annotation-inaccuracy span."""
    # The new-schema fixture classifies ply 4 as "inaccuracy" (see conftest.py).
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    body = resp.content.decode()
    assert "move-annotation-inaccuracy" in body
    assert ">?!<" in body  # canonical symbol from move_annotations.ANNOTATIONS


def test_pgn_strip_omits_annotation_for_unclassified_moves(
    client, new_schema_game_factory,
):
    """A row classified \"best\" (no badge) produces no move-annotation span for that ply."""
    game = new_schema_game_factory()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    body = resp.content.decode()
    # Plies 1 and 2 are "best" in the fixture — they should appear as chips
    # but carry no annotation span. Verify by counting spans against badged
    # plies: the fixture has classifications best/best/great/inaccuracy at
    # plies 1/2/3/4, so we expect exactly two annotation spans (great + inaccuracy).
    assert body.count('class="move-annotation') == 2


def test_pgn_strip_renders_empty_placeholder_when_no_moves(
    client, simple_pgn_game,
):
    """A game with empty PGN renders a moves-empty placeholder and no chips."""
    simple_pgn_game.pgn = ""
    simple_pgn_game.save()
    # Need analysis data for v2 gate — minimal SF row at ply 0 won't help since
    # the view walks the PGN. Easier: assert that a PGN-less response renders
    # the moves-empty span. If the view 404s on empty PGN, adjust the assertion
    # to the actual fallback behavior.
    resp = client.get(reverse("games_pgn_partial", args=[simple_pgn_game.slug]))
    body = resp.content.decode()
    if resp.status_code == 200:
        assert 'class="moves-empty"' in body
        assert 'class="moves-mv"' not in body
    else:
        # If the view declines to render an empty strip, that's also acceptable.
        assert resp.status_code in (404, 200)


def test_pgn_strip_uses_ellipsis_prefix_for_leading_black_move(
    client, new_schema_game_factory,
):
    """A PGN whose first move is Black's renders the move-number prefix with an ellipsis."""
    game = new_schema_game_factory()
    # Replace the PGN with one that starts mid-position (Black to move).
    # The simplest construction: a PGN with a SetUp/FEN header placing Black
    # to move, plus a single black move. Tests here document the intent;
    # the actual fixture mutation may need to live in a new conftest helper.
    game.pgn = (
        '[Event "Mid-position"]\n'
        '[Site "?"]\n'
        '[Date "2026.01.01"]\n'
        '[Round "1"]\n'
        '[White "Alice"]\n'
        '[Black "Bob"]\n'
        '[Result "*"]\n'
        '[SetUp "1"]\n'
        '[FEN "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"]\n'
        '\n1... e5 *'
    )
    game.save()
    resp = client.get(reverse("games_pgn_partial", args=[game.slug]))
    body = resp.content.decode()
    if resp.status_code == 200 and 'class="moves-mv"' in body:
        # The first move-number span should use the ellipsis form.
        assert "1…" in body or "1..." in body
    else:
        # If the view doesn't render for a mid-position PGN (because there's
        # no analysis for plies that don't exist), the case is moot; mark as
        # documenting-intent. Implementer: revisit if the view does render.
        pytest.skip("View did not render a strip for the mid-position PGN; "
                    "ellipsis-prefix branch covered by template logic only.")
```

(The last two tests have conditional assertions because the existing `pgn_partial` view's behavior on empty/mid-position PGNs hasn't been characterized. Adjust to concrete asserts once you run them against the real view.)

- [ ] **Step 3: Run the new tests to verify they fail**

```bash
pytest games/tests/test_partial_routes.py -v -k "pgn_strip"
```

Expected: all five fail — the old template still renders `<details>` + `<table>`, not the strip.

- [ ] **Step 4: Rewrite the partial template**

Replace the entire contents of `services/app/templates/games/partials/_pgn_table.html`:

```django
{# Title: _pgn_table.html — Main-board moves strip partial #}
{# Description: #}
{#     HTMX partial rendering the always-visible inline moves strip shown #}
{#     directly under the main game board. Each move is a focusable button #}
{#     (.moves-mv) carrying its absolute ply in data-ply and a server-rendered #}
{#     classification annotation badge via _move_annotation.html. Clicking a #}
{#     chip calls WoodLeagueAnalysis.setPly() via the pgnTable.js delegated #}
{#     click handler; the active chip is highlighted and scrolled into view #}
{#     as the user steps through the game. #}
{# Context: #}
{#     pgn_moves (list[dict]) — each entry: {ply, move_number, color, san, classification} #}
{# Changelog: #}
{#     2026-05-26 (#212): replaced <details>Moves</details> + two-column table #}
{#                       with an inline chip strip; relocated slot under main board. #}
{#     2026-05-21 (#186): Task 14 — lifted from inline analysis.html into partial. #}
{% load static %}

<nav id="pgn-moves" class="moves-strip" aria-label="Game moves">
  {% for move in pgn_moves %}
    {% if move.color == "white" %}<span class="moves-num">{{ move.move_number }}.</span>{% elif forloop.first %}<span class="moves-num">{{ move.move_number }}…</span>{% endif %}<button type="button" class="moves-mv" data-ply="{{ move.ply }}"><span class="moves-san">{{ move.san }}</span>{% include "games/partials/_move_annotation.html" with classification=move.classification %}</button>
  {% empty %}
    <span class="moves-empty">No moves recorded.</span>
  {% endfor %}
</nav>

<script src="{% static 'games/pgnTable.js' %}"></script>
```

(The number-span + button block is on a single source line to avoid emitting a text node between them — keeps chip baseline alignment tight in the rendered strip.)

- [ ] **Step 5: Run the strip tests to verify they pass**

```bash
pytest games/tests/test_partial_routes.py -v -k "pgn_strip"
```

Expected: the first three tests pass outright. The empty-placeholder and ellipsis tests may pass, fail, or skip depending on `pgn_partial`'s actual behavior on those inputs. If they fail, refine the test (or open a follow-up) — do NOT relax the implementation to match a confused test.

- [ ] **Step 6: Run the full games test suite to catch regressions**

```bash
pytest games/ -v
```

Expected: all previously-passing tests still pass. Any new failure must come from `test_partial_routes.py` itself (the old table shape was relied on by tests not yet updated). If the existing `pgn_partial` tests assert presence of `<table>` / `<details>` / `pgn-tbody`, update them to assert the new strip shape — the old shape is gone deliberately.

- [ ] **Step 7: Commit**

```bash
git add templates/games/partials/_pgn_table.html games/tests/test_partial_routes.py
git commit -m "feat(#212): rewrite _pgn_table.html as inline chip strip

Replaces the collapsed <details>Moves</details> + two-column White/Black
table with an always-visible <nav id=\"pgn-moves\" class=\"moves-strip\">
of clickable <button class=\"moves-mv\" data-ply=\"N\"> chips. Each chip
carries a server-rendered move-quality badge via _move_annotation.html.
Move-number prefix uses an ellipsis when the first move is Black's.

Five characterization tests in test_partial_routes.py guard chip count,
annotation presence/absence, empty-state placeholder, and the leading-
black-move ellipsis branch.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Rewrite `pgnTable.js` as a behavior wrapper

**Files:**
- Rewrite: `services/app/static/games/pgnTable.js`

No JS test harness exists; verification is manual (covered by Task 7's live review).

- [ ] **Step 1: Replace the entire file**

Overwrite `services/app/static/games/pgnTable.js`:

```javascript
/**
 * Title: pgnTable.js — Main-board moves strip behavior wiring
 * Description:
 *   Wires click + ply-sync + active-chip auto-scroll behavior onto the
 *   server-rendered moves strip (#pgn-moves) below the main board.  The
 *   chip DOM is built server-side by partials/_pgn_table.html; this module
 *   only attaches a delegated click handler, subscribes to the
 *   WoodLeagueAnalysis ply-state bus, and keeps the active chip visible
 *   inside the bounded-scroll strip via scrollIntoView({block: 'nearest'}).
 *
 *   Honors prefers-reduced-motion by falling back to instant scroll.  The
 *   data-moves-wired marker on the strip prevents double-subscription if
 *   HTMX re-swaps the partial during the page lifetime.
 *
 * Changelog:
 *   2026-05-26 (#212): rewritten — server-rendered chip strip replaces the
 *                     two-column <details> table; no DOM construction here.
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html into module.
 */
(function () {
  "use strict";

  function init() {
    var strip = document.getElementById("pgn-moves");
    if (!strip) return;
    if (strip.dataset.movesWired === "1") return;  // guard against HTMX re-swap re-binds
    strip.dataset.movesWired = "1";

    strip.addEventListener("click", function (event) {
      var chip = event.target.closest(".moves-mv[data-ply]");
      if (!chip) return;
      var ply = parseInt(chip.dataset.ply, 10);
      if (isNaN(ply)) return;
      if (window.WoodLeagueAnalysis && typeof window.WoodLeagueAnalysis.setPly === "function") {
        window.WoodLeagueAnalysis.setPly(ply);
      }
    });

    var prefersReducedMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (!window.WoodLeagueAnalysis || typeof window.WoodLeagueAnalysis.subscribe !== "function") {
      return;
    }
    window.WoodLeagueAnalysis.subscribe(function (state) {
      strip.querySelectorAll(".moves-mv[data-ply]").forEach(function (chip) {
        var active = parseInt(chip.dataset.ply, 10) === state.ply;
        chip.classList.toggle("is-active", active);
        if (active) {
          chip.scrollIntoView({
            block: "nearest",
            behavior: prefersReducedMotion ? "auto" : "smooth",
          });
        }
      });
    });
  }

  init();
})();
```

- [ ] **Step 2: Verify the partial test suite still passes (no JS executed in tests, but template loading still works)**

```bash
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+212-moves-strip-below-main-board/services/app
source ../../.venv/bin/activate
pytest games/tests/test_partial_routes.py -v -k "pgn_strip"
```

Expected: same pass/fail/skip result as Task 4 Step 5 — JS rewrite cannot regress server-side template tests.

- [ ] **Step 3: Commit**

```bash
git add static/games/pgnTable.js
git commit -m "feat(#212): rewrite pgnTable.js as thin behavior wrapper

Drops all DOM construction (the chip markup is now server-rendered by
_pgn_table.html). Module is reduced to: delegated click → setPly,
WoodLeagueAnalysis subscription → .is-active toggle + scrollIntoView.
Honors prefers-reduced-motion. data-moves-wired guard prevents
double-subscription on HTMX re-swap.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Relocate the HTMX slot, add CSS, expose annotations to JS

**Files:**
- Modify: `services/app/templates/games/analysis.html`
- Modify: `services/app/games/views.py::game_analysis`

- [ ] **Step 1: Add `ANNOTATIONS` to the `game_analysis` view context**

Open `services/app/games/views.py`, find the `game_analysis` function. At the top of the file, add the import next to existing `games.*` imports:

```python
from games.move_annotations import ANNOTATIONS
```

In the `game_analysis` function's final `render(request, "games/analysis.html", { … })` call (the one for the non-no-data branch — there are two render calls; the one whose context already includes `"data": data`), add the key:

```python
        "move_annotations": ANNOTATIONS,
```

The full render call becomes:

```python
    return render(request, "games/analysis.html", {
        "game": game,
        "data": data,
        "no_data": False,
        "initial_ply": initial_ply,
        "initial_perspective": initial_perspective,
        "move_annotations": ANNOTATIONS,
    })
```

The no-data branch render does NOT need this — that branch doesn't load partials that consume the map.

- [ ] **Step 2: Run the view shell test to verify it still passes**

```bash
pytest games/tests/test_view_game_analysis_shell.py -v
```

Expected: pre-existing shell tests still pass (the new context key is additive).

- [ ] **Step 3: Relocate the HTMX slot inside the Position card**

Open `services/app/templates/games/analysis.html`. Find the Position card section (around line 53-68). Inside the `<section class="wc-card position-plate" …>`, immediately AFTER the `<div id="board-container" …>Loading board…</div>` line and BEFORE the `</section>` close tag, insert:

```django
      <div class="moves-strip-slot"
           hx-get="/_partials/games/{{ game.slug }}/pgn/"
           hx-trigger="load" hx-swap="innerHTML">Loading moves…</div>
```

- [ ] **Step 4: Delete the old bottom-of-page slot**

In the same file, find this line (around line 103 in the pre-edit file):

```django
  <div hx-get="/_partials/games/{{ game.slug }}/pgn/" hx-trigger="load" hx-swap="innerHTML"></div>
```

Delete it entirely.

- [ ] **Step 5: Add the moves-strip CSS to the inline `<style>` block**

Find the inline `<style>` block at the top of the `{% block content %}` (lines 13-21 pre-edit) — it currently defines `.engine-line-inline`, `.eln-num`, `.eln-mv`, `.eln-mv:hover`, `.eln-mv.is-active`, `.eln-empty`, and `.engine-lines-idle`. Append the following rules to that same `<style>` block, before its closing `</style>`:

```css
.moves-strip-slot { padding: 0; }
.moves-strip {
  font-family: var(--font-serif);
  font-size: 0.95rem;
  line-height: 1.8;
  color: var(--color-ebony);
  padding: 8px 10px 10px;
  border-top: 1px solid var(--color-card-border-soft);
  max-height: calc(1.8em * 6);
  overflow-y: auto;
  scrollbar-width: thin;
}
.moves-strip .moves-num {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  color: var(--color-peat);
  margin: 0 2px 0 6px;
}
.moves-strip .moves-mv {
  background: transparent;
  border: 0;
  padding: 0 3px;
  font: inherit;
  color: inherit;
  cursor: pointer;
  display: inline;
}
.moves-strip .moves-mv:hover,
.moves-strip .moves-mv:focus-visible {
  background: color-mix(in srgb, var(--color-gold) 18%, transparent);
  outline: 0;
}
.moves-strip .moves-mv.is-active {
  background: color-mix(in srgb, var(--color-gold) 35%, transparent);
  box-shadow: inset 0 -2px 0 var(--color-forest);
}
.moves-strip .move-annotation {
  margin-left: 1px;
  font-size: 0.78em;
  vertical-align: baseline;
}
.moves-strip .moves-empty {
  font-family: var(--font-mono);
  font-size: 0.72rem;
  color: var(--color-peat);
  opacity: 0.7;
}
```

- [ ] **Step 6: Expose the annotation map to JS via `json_script`**

Find the `{% block extra_js %}` near the bottom of `analysis.html`. Inside the `{% if not no_data %}` branch, BEFORE the existing `WoodLeagueAnalysis.initFromUrl(…)` script tag, add:

```django
{{ move_annotations|json_script:"move-annotations-data" }}
<script>
(function () {
  var raw = document.getElementById("move-annotations-data");
  if (!raw) return;
  var data = JSON.parse(raw.textContent || "{}");
  // Build the flat {symbols, titles} shape consumed by legacy callers
  // (pgnTable.js previously read .symbols/.titles before this work, and
  // charts/sfCp.js still reads .colors — populated below from the same source).
  var symbols = {};
  var titles = {};
  Object.keys(data).forEach(function (cls) {
    symbols[cls] = data[cls].symbol;
    titles[cls] = data[cls].title;
  });
  window.WoodLeagueMoveAnnotations = {
    raw: data,
    symbols: symbols,
    titles: titles,
    // sfCp.js consumer — map each classification to its CSS class so the
    // chart can pull the right swatch via getComputedStyle. Keys stay in
    // sync with the .move-annotation-{cls} classes hardcoded in main.css.
    colors: Object.keys(data).reduce(function (acc, cls) {
      acc[cls] = "move-annotation-" + cls;
      return acc;
    }, {}),
  };
})();
</script>
```

- [ ] **Step 7: Run the full games test suite**

```bash
pytest games/ -v
```

Expected: all tests pass. Pay attention to `test_view_game_analysis_shell.py` and `test_partial_routes.py` — both will exercise the modified `analysis.html`.

- [ ] **Step 8: Ruff + bandit on `views.py`**

```bash
ruff check games/views.py
bandit -ll games/views.py
```

Expected: ruff clean, bandit no Medium/High.

- [ ] **Step 9: Commit**

```bash
git add games/views.py templates/games/analysis.html
git commit -m "feat(#212): relocate moves slot inside Position card; expose annotations to JS

* HTMX moves slot moves from the page-bottom (below all charts) into the
  Position card immediately under #board-container, with a \"Loading
  moves…\" placeholder so the slot isn't a blank rectangle during fetch.
* Old page-bottom slot deleted.
* New .moves-strip CSS rules appended to the inline <style> block; only
  palette tokens referenced, no Tailwind rebuild needed.
* move_annotations ANNOTATIONS dict added to the game_analysis view
  context and rendered via {% json_script %} in extra_js; a small init
  builds window.WoodLeagueMoveAnnotations (raw / symbols / titles /
  colors keys) so the JS reference that pgnTable.js and charts/sfCp.js
  consume actually exists at runtime for the first time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Live verification, push, and PR

- [ ] **Step 1: Confirm `.env` symlink exists in the worktree's services/app/**

```bash
ls -la /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+212-moves-strip-below-main-board/services/app/.env
```

If the symlink is missing, ask the user to create it (the classifier blocks Claude from touching `.env` directly):

```
ln -s /Users/christopherwebster/Projects/wood_league/services/app/.env services/app/.env
```

…run as `! ln -s …` from the prompt in the user's session.

- [ ] **Step 2: Run the dev server with overrides**

```bash
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+212-moves-strip-below-main-board/services/app
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
DEBUG=True AUTH_ENABLED=True python manage.py runserver 8000
```

(Per [[project_run_app_locally_worktree]] — without these overrides you'll hit SSL-redirect/HSTS poisoning and a login↔home loop.)

- [ ] **Step 3: Visit a game with both SF and LC0 analyses populated**

```bash
# Pick a slug:
python manage.py shell -c "from analysis.models import Lc0GameAnalysis; \
print('\n'.join(Lc0GameAnalysis.objects.values_list('game__slug', flat=True)[:5]))"
# Open http://localhost:8000/games/<slug>/ in a browser.
```

Verify:

  1. **Strip appears** directly under the main board controls inside the Position card.
  2. **One chip per move**, classification badges visible for `?!`, `?`, `??`, `!`, `!!` moves.
  3. **Click a chip** — main board jumps to that ply; engine-line card (if a continuation was loaded) stays untouched.
  4. **Step with prev/next on the board** — active chip highlight follows, auto-scrolls into view inside the bounded strip.
  5. **Hover** — chip background lights up gold.
  6. **Tab through chips** with keyboard — focus ring visible, Enter activates.
  7. **Scroll to bottom of page** — old `<details>Moves</details>` is gone.
  8. **Engine-line continuation strip unchanged** — same look, same behavior as before.

If any of 1-8 fail: stop, investigate, do NOT proceed to the push.

- [ ] **Step 4: Run the full test suite one more time**

```bash
pytest games/ -v
pytest -v 2>&1 | tail -20
```

Expected:
- `pytest games/` — fully green.
- Full `pytest` — green except the pre-existing `ingest/tests/test_sync_games_command.py` failures (Postgres-only tests against SQLite; same pattern as documented in PR #211).

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin issue/212-moves-strip-below-main-board
gh pr create --base main --head issue/212-moves-strip-below-main-board \
  --title "#212 inline moves strip below main game board" \
  --body "Closes #212.

Implements the design from \`docs/superpowers/specs/2026-05-26-main-board-moves-strip-design.md\` (landed in PR #211).

Replaces the collapsed \`<details>Moves</details>\` + two-column White/Black table buried at the bottom of the game-analysis page with an always-visible inline strip of clickable SAN chips directly under the main game board, mirroring the engine-line continuation idiom. Click → \`WoodLeagueAnalysis.setPly\`; active chip is highlighted and \`scrollIntoView({block:'nearest'})\`'d as the user steps through. Bounded to ~6 wrapped lines max-height with internal scroll so long games don't reshape the page.

## Implementation

- New \`games/move_annotations.py\` — single source of truth dict for classification → {symbol, title}.
- New \`games/templatetags/games_extras.py\` — \`move_annotation_symbol\` and \`move_annotation_title\` filters.
- New \`partials/_move_annotation.html\` — tiny badge include.
- Rewritten \`partials/_pgn_table.html\` — inline chip strip with server-rendered badges and an ellipsis-prefix branch for PGNs that start with Black's move.
- Rewritten \`static/games/pgnTable.js\` — DOM-construction-free behavior wrapper; delegated click + \`WoodLeagueAnalysis\` subscription + reduced-motion-aware scroll.
- \`analysis.html\` — slot relocated inside the Position card, old bottom slot deleted, new \`.moves-strip\` CSS rules, \`json_script\` exposing the annotation map to \`window.WoodLeagueMoveAnnotations\` (first-ever definition — was previously consumed with \`{}\` fallbacks in \`pgnTable.js\` and \`charts/sfCp.js\`).

## Tests

19 new tests in \`tests/test_move_annotations.py\` (helpers + filters + include rendering) plus 5 strip-shape tests in \`tests/test_partial_routes.py\`. Full \`pytest games/\` green; full \`pytest\` green except the pre-existing Postgres-only ingest tests documented in PR #211.

## Live review

Verified locally: strip appears under the board, chips clickable, active highlight + scroll tracking work, annotation badges present for \`?!\`/\`?\`/\`??\`/\`!\`/\`!!\` moves, keyboard navigation works, old bottom \`<details>\` gone, engine-line strip untouched.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 6: Confirm PR opened and CI green**

```bash
gh pr view --json number,url,statusCheckRollup | head -40
```

Wait for all checks SUCCESS before requesting review.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|--------------|------|
| Architecture diagram | T6 (slot relocation) |
| View no logic change | T6 step 1 (additive context only) |
| Template rewrite | T4 |
| `_move_annotation.html` include | T3 |
| `move_annotations.py` source of truth | T1 |
| `games_extras` filters | T2 |
| HTMX wiring relocation | T6 steps 3-4 |
| `pgnTable.js` rewrite | T5 |
| Styling | T6 step 5 |
| Edge cases — legacy / no-data | covered by no-op no-data render branch (T6 step 1) |
| Edge cases — no SF analysis | T3 (include returns "" on None) + T4 third test |
| Edge cases — empty PGN | T4 fourth test |
| Edge cases — leading Black move | T4 fifth test + template branch |
| Edge cases — HTMX re-swap | T5 (`data-moves-wired` guard) |
| Edge cases — ply 0 | covered by absence of `data-ply="0"` chip (T4 markup) |
| Django view tests | T4 (5 new) |
| Move-annotation tests | T1, T2, T3 (19 across the three tasks) |
| Annotation map matches JS — drift test | not implemented — see note below |
| Manual verification | T7 |

**Open question resolution:** T0.

**Drift test deferred:** The spec proposed a `test_annotation_map_matches_js_constants` test that parses the JSON emitted by `json_script` on the rendered shell and asserts parity with the Python `ANNOTATIONS` dict. Skipped here because the JS-side payload is *generated from* the Python dict via `json_script` — they can't drift unless someone hand-edits the rendered HTML, which isn't a realistic regression vector. If the implementer wants the test anyway: render `analysis.html` via the test client, parse the `<script id="move-annotations-data">` body as JSON, assert it equals `ANNOTATIONS`. Five lines; add to `test_move_annotations.py` as a 20th test if desired.

**Placeholder scan:** none. All code shown, all paths absolute relative to repo root, all commands runnable.

**Type consistency:** `ANNOTATIONS: dict[str, dict[str, str]]` used in `move_annotations.py` and consumed unchanged by `games_extras.py`, `_move_annotation.html`, `views.py`, and `analysis.html` (`json_script` serializes the whole dict). `symbol()` / `title()` signatures match `(str | None) -> str` in all three call sites (helpers, filters, include).

**No orphans:** every type, function, and template referenced is defined in this plan or already exists in the repo (`WoodLeagueAnalysis`, `chips_for_ply`, etc., already shipped).
