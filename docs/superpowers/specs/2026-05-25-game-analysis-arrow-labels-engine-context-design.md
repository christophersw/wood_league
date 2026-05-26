# Game Analysis — Arrow Labels & Engine-Line Context (Design)

**Date:** 2026-05-25
**Issue:** #208 (label `upgrade`, milestone v1) — game-analysis page restyle, continued.
**Branch / worktree:** `issue/208-restyle-game-analysis-page` (`.claude/worktrees/issue+208-restyle-game-analysis`)
**Prior specs:** `2026-05-22-game-analysis-restyle-design.md` (cards + Move Analysis section);
plan `docs/superpowers/plans/2026-05-23-game-analysis-move-section.md` ("Live-review findings").

## Context

The Move Analysis section landed but a live review left three open issues, and the user
added a fourth. This spec covers all four as one increment so a single implementation plan
can reference it. Two are bug fixes (chips, alignment); two are design changes (arrow
labels, engine-line context).

Design language is unchanged ("Du Bois plate"): sharp corners (`border-radius:0`), ebony
top-border rules (not shadows), cream plates on parchment, Playfair-SC uppercase forest
titles, DM-Mono uppercase micro-labels, EB-Garamond names/numbers. All colours via `:root`
tokens in `services/app/static/css/main.css`.

---

## Item 1 — Move chips render unstyled (bug)

**Symptom:** the form-2 chip tiles have no styling in the browser.

**Root cause:** chip rules live in the standalone `services/app/static/games/moveChips.css`,
`<link>`ed only from inside `_move_chips.html`, which is injected via HTMX `innerHTML` into
`#move-chips`. `base.html` loads only the compiled `tailwind.css`; the injected `<link>` is
not reliably applied to the swapped content.

**Fix:** move every rule from `moveChips.css` into `main.css` under `@layer components`
(alongside `.wc-card` / `.card-*` / `.move-annotation-*`), so the chip styles ship in the
globally-loaded `tailwind.css` — the original spec intent ("shared chip/plate styling moves
into main.css"). Then:

- Delete the `<link rel="stylesheet" href="…moveChips.css">` line from `_move_chips.html`.
- Delete the `services/app/static/games/moveChips.css` file.
- Rebuild `tailwind.css` under **Node 22** (`bin/build_tailwind.sh`) and commit the artifact.

**Verify:** every `move-annotation-*` band top-rule colour resolves (including the four LC0
draw bands), the muted `.move-chip--lc0_draw` variant still reads correctly, and chips are
sharp parchment tiles — no rounded pills.

---

## Item 2 — "THIS MOVE" plate not aligned with the boards (bug)

**Symptom:** the full-width THIS MOVE chips plate's left/right edges don't line up with the
`1fr 1fr` `#boards-container` grid below it (POSITION left edge / ENGINE LINE right edge).

**Fix:** make the `#move-chips` plate share the boards-container's horizontal box — same
width and horizontal margin/padding, no stray `max-width` or auto-margin on the `.wc-card`.
Both are block children of the same `.pg-section`, so the end state is: THIS MOVE's left
edge aligns with the POSITION plate's left edge and its right edge with the ENGINE LINE
plate's right edge. Confirm by live review (no unit test for pixel alignment).

---

## Item 3 — Board arrow labels: parchment tag + engine rule (design)

**Current:** `buildArrowElement` (`_board_partial.html` JS, ~347–371) draws the label as
plain `<text>` rotated along the arrow shaft, mono 11px/700, white halo stroke, filled
tobacco (SF) / denim (LC0). Text is `arrowData.label` = `"SF +0.34"` / `"Lc0 +12%"`
(from `board_builder._arrow_label`). Reads as unrefined and tilts with the arrow.

**Chosen treatment (mockup "C"):** a small **sharp, horizontal tag** placed near the
arrowhead (not rotated):

- Parchment fill (`--color-parchment`), 1px hairline border `color-mix(in srgb,
  var(--color-peat) 35%, transparent)`.
- A 2.5px **engine-colour top rule**: `--color-tobacco` for SF, `--color-denim` for LC0
  (same form-2 tile idiom as the move chips).
- Eval text in the engine colour, DM-Mono ~10px/700.
- **Drop the engine prefix** — colour carries the engine, so the tag shows the eval only
  (`+0.34`, `+12%`). Negative values keep the existing unicode-minus formatting.

**Implementation notes:**

- Build the tag in `buildArrowElement` as an SVG `<g>` containing a `<rect>` (fill + border),
  a thin `<rect>` top rule in the engine colour, and a centred `<text>` — replacing the
  current rotated single `<text>`. Position horizontally at ~0.66 along the shaft, offset
  ~15px perpendicular so it clears the arrow line. Tag stays axis-aligned (no rotation).
- Change `board_builder._arrow_label` to return the eval only (no `"SF "/"Lc0 "` prefix);
  update its docstring and the tests that assert the prefix.
- Update `.board-arrow-label` / `--sf` / `--lc0` CSS in `_board_partial.html` to style the
  new tag parts (text fill per engine; the rect/rule colours can be set on the elements).
- **Accessibility:** because the visible prefix is gone, include the engine name in the
  arrow group's `title` / `aria-label` (e.g. "Stockfish best line +0.34") so the engine is
  still announced and shown on hover.

---

## Item 4 — Engine-line context becomes bot player names (design)

**Idea:** the engine-line board shows a *hypothetical perfect continuation* — effectively
the engine playing itself. So instead of a separate header strip, label the engine-line
board's two player slots with the **bot identity and its search setting**, mirroring the
main board's player labels. This reads as "bot vs bot, played perfectly."

**Label text:**
- SF:  `SF bot · depth {data.engine_depth}`   → e.g. `SF bot · depth 22`
- LC0: `LC0 bot · nodes {data.lc0_engine_nodes:,}` → e.g. `LC0 bot · nodes 25,000`
- Separator is a middot `·`; `depth`/`nodes` lowercase; nodes comma-grouped.
- Fallback when the setting is `None`: show just `SF bot` / `LC0 bot` (omit the `· …`).
- The same bot string appears on **both** the top and bottom player slots (both sides are
  the bot). Keep the side marker on each (`♚ Black` / `♔ White`) to mirror the main board.

**Markup / data flow (basic HTMX — no new client logic):**

- `engine_line_partial` (`views.py:400`) already has `params.engine` and the run-level
  `data.engine_depth` / `data.lc0_engine_nodes`. Compute `bot_label` there and the
  top/bottom side + king symbol from `params.orientation` (same derivation as the board
  view), and pass them to `_engine_line_partial.html`.
- In `_engine_line_partial.html`, replace the empty `engine-line-context-bar` (top) and
  `engine-line-player-spacer` (bottom) with real player-label divs reusing the main board's
  `.player-label` / `.player-side` / `.player-name` classes (with the server-side
  `player-label-no-top` / `-no-bottom` border-rule classes), so both boards are visually
  identical except for the names. The bot name uses a mono variant (matching the mockup).
- The partial is swapped into `#engine-lines-container` by the existing `htmx.ajax()` call
  in `loadEngineLine`; on flip the partial reloads with the new orientation, so the
  side markers/border rules are correct without JS.

**Removals (this is mostly deletion):**

- Delete the `engine-lines-header` `<div>` from `analysis.html` (the old prompt/context
  strip) and the `engineLinesHeader.textContent = …` block in `_engine_line_partial.html`.
- Delete `_applyEngineLineBorderStyles` from `engineLines.js` and its call sites
  (`applyBorderStyles`, the `clearBoard` header reset that targeted `engine-lines-header`,
  and the perspective-change re-style) — border rules are now server-side classes. Drop the
  `header` entry from `_getEngineLineElements`.
- Drop `context_label` from the view's render context (no longer used).

**Idle state (before any arrow click):**

- The `engine-lines-context` span in the plate header stays a quiet `—`.
- Show the prompt — "Click an engine arrow on the board to explore the continuation." —
  centred in the empty `#engine-lines-container` body. The HTMX swap replaces it with the
  engine board the moment a line loads (so it is naturally hidden on load; nothing to
  toggle).

---

## Out of scope

Win%/SF-cp/LC0-WDL charts, the PGN panel, and the page hero/empty-state remain for a later
increment (tracked in the prior spec's remaining-elements list).

## Testing

- **Item 1:** existing chip tests still pass; add/confirm a test that the chips partial no
  longer emits a `moveChips.css` `<link>`. Live-review the rendered tiles.
- **Item 3:** update `board_builder._arrow_label` tests for the prefix-dropped eval text;
  live-review the tag look on a real board (both engines, both orientations).
- **Item 4:** view test that `_engine_line_partial` renders the bot label
  (`SF bot · depth …` / `LC0 bot · nodes …`) in both player slots and no longer contains
  `engine-lines-header`; live-review idle prompt → arrow click → bot-labelled board, and
  flip.
- **Tailwind:** rebuild `tailwind.css` under Node 22 after the main.css change (Item 1) and
  any new utility classes; commit the artifact or the css-staleness CI gate fails.
- JS behaviour has no unit harness — verify Items 3 and 4 by live review per
  `project_run_app_locally_worktree` (`DEBUG=True AUTH_ENABLED=True`).
