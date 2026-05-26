# Main-Board Moves Strip — Design

**Status:** Approved 2026-05-26 (replaces the collapsed-by-default `<details>Moves</details>` table at the bottom of the game-analysis page with an always-visible inline strip directly under the main board, mirroring how the engine-line continuation strip sits under the engine-line board.)

## Problem

The game-analysis page renders a `_pgn_table.html` partial that lists every move with SF classifications, click-to-set-ply, and active-ply highlighting. In practice users can't find it: the slot lives at the bottom of `analysis.html`, *below* three full-width charts, and the partial itself is wrapped in a `<details>` that's collapsed by default. The page reads as "no move list at all" until you scroll past every chart and click a disclosure.

The engine-line card next to the main board solves the same problem differently: it renders the continuation as an inline flowing strip of clickable SAN chips, directly under the engine-line board controls, always visible. That visual idiom — strip-under-board — is what the user wants for the main board's moves.

## Goal

Replace the bottom `<details>Moves</details>` table with an inline moves strip located *inside the Position card, directly under the main board controls*, that:

- Lists every PGN ply as a clickable chip.
- Carries the same per-move classification annotation badges (`?!`, `??`, `!`, `!!`, etc.) the table carries today.
- Clicking a chip calls `WoodLeagueAnalysis.setPly(ply)` to sync the board and every other ply-tracking partial.
- The current ply's chip gets an `.is-active` highlight and `scrollIntoView({block:'nearest', behavior:'smooth'})` as the user steps through the game.
- Renders inside a bounded scroll container so a 200-ply game doesn't push the rest of the page out of view.

## Non-goals

- Touching the engine-line continuation strip. The two strips stay in separate CSS namespaces (`.moves-strip` vs `.engine-line-inline`) so they can diverge in future.
- Adding a JS test harness — the JS surface (~30 lines) is verified manually via the existing live-review flow.
- Per-move classification *colour* on chip backgrounds. Annotation badges only. (A future restyle iteration could add chip-level colour; out of scope here.)

## Architecture

One new piece, three relocations, one deletion.

- **New:** server-rendered inline moves strip emitted by the existing `games.views.pgn_partial` view. The view's data computation is unchanged — same `pgn_moves` list of `{ply, move_number, color, san, classification}` dicts. Only the template shape changes.
- **Relocated:** the partial's HTMX slot moves from `analysis.html:103` (page-bottom, below all charts) to inside the Position card at `analysis.html:67`, immediately under `#board-container`. The Engine Line card on the right is untouched.
- **Relocated:** the click + active-class + scroll behavior. Today it lives in `pgnTable.js` operating on a `<table>`. Rewritten in place to operate on the new chip markup. Filename stays `pgnTable.js`.
- **Deleted:** the `<details>` wrapper, the two-column `<table>`, the `json_script` payload, and the JS DOM-construction loop. All gone.
- **Boundary:** the strip communicates with the rest of the page only via the existing `WoodLeagueAnalysis` ply-state bus. No new global state, no DOM coupling to other partials.

```
Position card
├─ <header class="wc-card__head"> [unchanged]
├─ #board-container          [HTMX → /_partials/games/<slug>/board/]
└─ .moves-strip-slot         [HTMX → /_partials/games/<slug>/pgn/]    ← new location

(old page-bottom slot at analysis.html:103 is removed.)
```

## Server-side: view + template

### View — `services/app/games/views.py::pgn_partial`

**No logic change.** The view continues to walk the PGN mainline, attach SF classifications from new-schema `MoveAnalysis` rows, and return a `pgn_moves` context list. Same context key, same shape. Only the rendered template's markup differs.

### Template — `services/app/templates/games/partials/_pgn_table.html` (rewrite in place)

```django
{# Title: _pgn_table.html — Main-board moves strip partial #}
{# Description: #}
{#     HTMX partial rendering the inline moves strip shown directly under the #}
{#     main game board. Each move is a focusable <button class="moves-mv"> chip #}
{#     carrying its absolute ply in data-ply and a server-rendered classification #}
{#     annotation badge. Clicking a chip calls WoodLeagueAnalysis.setPly() via #}
{#     the pgnTable.js delegated click handler; the active chip is highlighted #}
{#     and scrolled into view as the user steps through the game. #}
{# Changelog: #}
{#     2026-05-26 (#new): replace <details>Moves</details> + two-column table #}
{#                       with inline strip; relocate slot under main board. #}
{% load static %}

<nav id="pgn-moves" class="moves-strip" aria-label="Game moves">
  {% for move in pgn_moves %}
    {% if move.color == "white" %}
      <span class="moves-num">{{ move.move_number }}.</span>
    {% elif forloop.first %}
      {# Game starts mid-position with Black to move — render ellipsis prefix. #}
      <span class="moves-num">{{ move.move_number }}…</span>
    {% endif %}
    <button type="button" class="moves-mv" data-ply="{{ move.ply }}">
      <span class="moves-san">{{ move.san }}</span>
      {% include "games/partials/_move_annotation.html" with classification=move.classification %}
    </button>
  {% empty %}
    <span class="moves-empty">No moves recorded.</span>
  {% endfor %}
</nav>

<script src="{% static 'games/pgnTable.js' %}"></script>
```

### New include — `services/app/templates/games/partials/_move_annotation.html`

```django
{# Tiny include: emit a classification annotation badge, or nothing. #}
{# Used by the moves strip and any future per-move annotation surface. #}
{% load games_extras %}
{% with sym=classification|move_annotation_symbol %}
  {% if sym %}<span class="move-annotation move-annotation-{{ classification|lower }}"
                    title="{{ classification|move_annotation_title }}">{{ sym }}</span>{% endif %}
{% endwith %}
```

### Annotation source of truth — `services/app/games/move_annotations.py` (new file)

The current symbol/title map is defined client-side as `window.WoodLeagueMoveAnnotations`. Server-side rendering needs the same map. Consolidating into one Python source, with the JS object generated from it via `json_script` in the shell template:

```python
"""
Title: move_annotations.py — Single source of truth for SF move-annotation badges.
Description:
    Maps SF move classifications ("brilliant", "best", …, "blunder") to the
    inline annotation symbol (?!, ??, !, !!, …) and tooltip title rendered
    next to each move in the moves strip and any future per-move annotation
    surface. Consumed server-side by the _move_annotation.html include and
    client-side via window.WoodLeagueMoveAnnotations (generated by the
    analysis shell template's extra_js block from this same dict).
"""

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
    """Return the annotation symbol for a classification, or "" if none."""
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("symbol", "")

def title(classification: str | None) -> str:
    """Return the annotation tooltip title for a classification."""
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("title", classification)
```

A small template-tag library `games/templatetags/games_extras.py` exposes `move_annotation_symbol` and `move_annotation_title` filters that call into this module. The analysis shell's `extra_js` block emits `{{ ANNOTATIONS|json_script:"move-annotations-data" }}` and `window.WoodLeagueMoveAnnotations` is built from that script tag in a tiny inline init.

(Exact symbol values above are placeholders for what's currently in `WoodLeagueMoveAnnotations`. The implementation phase will mirror whatever's actually defined there; the consolidation is the only change.)

### HTMX wiring — `services/app/templates/games/analysis.html`

Add at line 67 (inside Position card, after `#board-container`):

```django
<div class="moves-strip-slot"
     hx-get="/_partials/games/{{ game.slug }}/pgn/"
     hx-trigger="load" hx-swap="innerHTML">Loading moves…</div>
```

Remove the old slot at line 103:

```django
{# DELETED: <div hx-get="/_partials/games/{{ game.slug }}/pgn/" hx-trigger="load" hx-swap="innerHTML"></div> #}
```

## Client-side — `services/app/static/games/pgnTable.js` (rewrite)

```javascript
/**
 * Title: pgnTable.js — Main-board moves strip behavior wiring
 * Description:
 *   Wires click + ply-sync + active-chip auto-scroll behavior onto the
 *   server-rendered moves strip (#pgn-moves) below the main board. The
 *   strip's chip DOM is built server-side by _pgn_table.html; this module
 *   only attaches a delegated click handler, subscribes to the
 *   WoodLeagueAnalysis ply-state bus, and keeps the active chip visible.
 *
 * Changelog:
 *   2026-05-26 (#new): rewritten — server-rendered chip strip replaces the
 *                     two-column table; no DOM construction in JS.
 *   2026-05-21 (#186): Task 14 — lifted from inline analysis.html.
 */
(function () {
  "use strict";

  function init() {
    var strip = document.getElementById("pgn-moves");
    if (!strip) return;
    if (strip.dataset.movesWired === "1") return;  // HTMX re-swap guard
    strip.dataset.movesWired = "1";

    strip.addEventListener("click", function (event) {
      var chip = event.target.closest(".moves-mv[data-ply]");
      if (!chip) return;
      WoodLeagueAnalysis.setPly(parseInt(chip.dataset.ply, 10));
    });

    var prefersReducedMotion = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    WoodLeagueAnalysis.subscribe(function (state) {
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

Key choices:

- **Delegated click handler** on the strip root, not per-chip.
- **`data-moves-wired` re-entry guard** prevents double-subscription if HTMX re-swaps the partial.
- **`prefers-reduced-motion`** check disables smooth scroll for users who opt out of animation.
- **No JSON parsing, no DOM build loop, no `WoodLeagueMoveAnnotations` consumption.** Annotations are server-rendered.

## Styling — inline in `analysis.html`

New CSS rules added to the existing `<style>` block at `analysis.html:13-21` (next to `.engine-line-inline` and friends):

```css
.moves-strip-slot { padding: 0; }
.moves-strip {
  font-family: var(--font-serif);
  font-size: 0.95rem;
  line-height: 1.8;
  color: var(--color-ebony);
  padding: 8px 10px 10px;
  border-top: 1px solid var(--color-card-border-soft);

  /* Bounded scroll container so long games don't push the page around;
     active-chip scrollIntoView keeps the current move visible. */
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

Notes:

- **Parallel namespace** (`.moves-strip`) rather than reusing `.engine-line-inline`. Visual idiom is identical today; the namespace lets the two diverge cleanly in future.
- **6-line cap** (`max-height: calc(1.8em * 6)`) ≈ ~170px at 0.95rem font. Tunable.
- **No Tailwind rebuild needed** — only palette tokens (`--color-*`) are referenced. Per [[project_tailwind_build]] this changes nothing in `tailwind.css`.

## Edge cases

- **Legacy / no-data games** — `analysis.html` short-circuits to the reanalyze banner via `{% if no_data %}`; the new slot lives in the `{% else %}` branch, never requested for those games.
- **PGN present but no SF analysis** — `move.classification` is `None`/`""` for every move; `_move_annotation.html` emits nothing; chips render as plain SAN. Strip still works for navigation.
- **No PGN / empty `pgn_moves`** — `{% empty %}` branch emits `<span class="moves-empty">No moves recorded.</span>` so the strip degrades gracefully.
- **Single-move game** — strip shows one chip; no special case.
- **Game starts mid-position with Black to move** — `{% elif forloop.first %}` clause renders the move-number prefix with an ellipsis (`{{ move_number }}…`) instead of a period.
- **HTMX re-swap of the partial** — `data-moves-wired` guard prevents double-subscription.
- **Very long games (200+ plies)** — active-class toggle is a single querySelectorAll + forEach per ply-change event; <1ms.
- **Ply 0 (start position)** — no chip has `data-ply="0"`, no chip is active. Correct.

## Testing

Three test layers.

### Django view tests — `services/app/games/tests/test_partial_routes.py`

Extending existing `pgn_partial` coverage:

- `test_pgn_strip_renders_one_chip_per_move` — new-schema game with 4 plies produces 4 `moves-mv` chips with `data-ply="1"` through `data-ply="4"`.
- `test_pgn_strip_emits_annotation_for_classified_moves` — a row classified `"blunder"` produces a `move-annotation-blunder` span inside the relevant chip.
- `test_pgn_strip_omits_annotation_for_unclassified_moves` — a row with `classification=None` → chip has no `move-annotation` element.
- `test_pgn_strip_renders_empty_placeholder_when_no_moves` — game with empty PGN → response contains `moves-empty` element, no chips.
- `test_pgn_strip_uses_ellipsis_prefix_for_leading_black_move` — PGN starting with Black to move → first chip preceded by `{move_number}…` not `{move_number}.`.

### Move-annotation consolidation test — `services/app/games/tests/test_move_annotations.py` (new)

- `test_annotation_symbol_returns_empty_for_none_or_unknown` — guards against KeyError regressions.
- `test_annotation_title_falls_back_to_classification_when_unknown` — guards the `.get(…, classification)` fallback.
- `test_annotation_map_matches_js_constants` — parse the JSON emitted by `json_script` on the rendered analysis shell and assert key/value parity with `ANNOTATIONS`. Catches drift between the Python and JS sides.

### Manual verification (no JS test harness)

After implementation, follow the standard live-review flow used for #208 (DEBUG=True + AUTH_ENABLED=True dev server) and confirm:

1. Strip appears directly under the main board controls inside the Position card.
2. Each move is clickable; clicking jumps the board to that ply.
3. Active ply is highlighted; stepping with prev/next on the board scrolls the active chip into view.
4. Annotation badges appear for classified moves (`?!`, `??`, etc.) and are absent for unclassified ones.
5. Old bottom-of-page `<details>Moves</details>` is gone.
6. Engine-line continuation strip is unchanged.

## Implementation footprint

- **Modified:** `services/app/games/views.py` (no logic change; possibly add `ANNOTATIONS` passthrough to the shell context if needed for `json_script`).
- **Modified:** `services/app/templates/games/analysis.html` (slot relocation + delete old slot + new CSS rules in inline `<style>`).
- **Rewritten:** `services/app/templates/games/partials/_pgn_table.html`.
- **Rewritten:** `services/app/static/games/pgnTable.js`.
- **New:** `services/app/games/move_annotations.py`.
- **New:** `services/app/templates/games/partials/_move_annotation.html`.
- **New:** `services/app/games/templatetags/games_extras.py` (template filters for the annotation include).
- **New:** `services/app/games/tests/test_move_annotations.py`.
- **Extended:** `services/app/games/tests/test_partial_routes.py`.

Gate per-commit: ruff, mypy, bandit -ll on edited `.py` files, `pytest games/`. Tailwind rebuild *not* required.

## Open questions

None at design time. Implementation phase will resolve:

- Exact `WoodLeagueMoveAnnotations` symbol/title values (read at implementation start, mirrored into `ANNOTATIONS`).
- Where the JS-side `window.WoodLeagueMoveAnnotations` is currently defined (the consolidation needs to replace that definition; if it lives outside the shell template, we relocate the `json_script` accordingly).
