# Game Analysis Page Restyle — Design Spec

**Issue:** #208 — Restyle the Game Analysis page (incremental, element by element)
**Date:** 2026-05-22
**Status:** SF + LC0 cards built; Move Analysis section locked; charts / PGN / hero pending (incremental)

## Problem

The game-analysis page rewrite left the page styled in a generic "rounded card +
drop shadow" idiom that clashes with the rest of the redesigned site. The site
otherwise uses a consistent **"Du Bois plate"** design language. This spec
restyles the page **one element at a time**, starting with the Stockfish (SF) and
LC0 stat cards. Each element is reviewed live in the running app on the
`issue/208-restyle-game-analysis-page` worktree before moving on.

## Design language to match (the "Du Bois plate")

Established in `services/app/static/css/main.css` and used by `.pg-head`,
`.filter-panel`, `.wc-table`, `.wc-btn`:

- **Sharp corners** — `border-radius: 0` (no rounded cards, no soft shadows).
- **Border-rules, not shadows** — a heavy ebony top rule (`2–3px solid
  var(--color-ebony)`) plus thin enclosing borders.
- **Backgrounds** — `var(--color-cream)` panels on a `var(--color-parchment)` page.
- **Titles** — `var(--font-display)` (Playfair Display SC), uppercase, letter-spaced,
  in `var(--color-forest)`.
- **Micro-labels** — `var(--font-mono)` (DM Mono), uppercase, ~0.6rem, letter-spaced,
  in `var(--color-peat)`.
- **Numbers** — `var(--font-serif)` (EB Garamond), `font-variant-numeric: tabular-nums`.

## Stockfish card — locked design

File: `services/app/templates/games/partials/_card_sf.html` (and its `<style>` block).
The LC0 card (`_card_lc0.html`) gets the matching treatment as the next step.

### Frame
- `.wc-card` becomes a Du Bois plate: `background: var(--color-cream)`;
  `border: 1.5px solid color-mix(in srgb, var(--color-peat) 22%, transparent)`;
  `border-top: 3px solid var(--color-ebony)`; `border-radius: 0`; **no box-shadow**.
- Header: card title in Playfair uppercase forest (`STOCKFISH`), with a thin
  bottom hairline rule (like `.pg-head`). The `ⓘ` run-info tooltip (existing
  `.card-info-tooltip`) stays.
- Two sides retained: White then Black, each with a mono uppercase side-title
  (e.g. `magnus · White`).

### Metrics as stat tiles
Per side, the three SF metrics render as a **3-up grid of sharp stat tiles**
(replacing the old `.metric` rows):
- Each tile: sharp border with a `2px solid var(--color-forest)` top rule,
  `var(--color-parchment)` background.
- Layout: mono uppercase label on top, serif tabular number below.
- Tiles: **Accuracy**, **ACPL**, **Win% drop** (label shortened from
  "Avg Win% drop" to fit; full name in tooltip).

### Move-quality bar (prominent + labeled)
Replaces the old thin 8px `.sf-bar`:
- **34px tall**, sharp corners, **2px gap** between segments.
- Each segment is flex-weighted by its count, `min-width` ~2.6rem so labels fit.
- Each segment shows its **glyph + count** inline, in DM Mono, with readable
  text color per background.
- A small mono "MOVE QUALITY" caption sits above the bar with a "— what's this?"
  affordance.

### Glyph ↔ band mapping (conventional)
Applies to both the in-bar segment labels and the legend. Segments with no glyph
show **count only** (color carries the band).

| Band | Glyph | Palette token |
|---|---|---|
| Brilliant | `!!` | `--color-teal` |
| Great | `!` | `--color-leaf` |
| Best | *(none)* | `--color-emerald` |
| Excellent | *(none)* | `--color-leaf` |
| Good *(LC0 only)* | *(none)* | `--color-leaf` |
| Inaccuracy | `?!` | `--color-saffron` |
| Mistake | `?` | `--color-ember` |
| Blunder | `??` | `--color-vermilion-bright` |

Note: SF emits Brilliant/Great/Best/Excellent/Inaccuracy/Mistake/Blunder
(no "Good"); the LC0 severity axis emits Best/Excellent/Good/Inaccuracy/Mistake/
Blunder (no Brilliant/Great). Segments are only rendered when count > 0
(existing template already guards this).

## Tooltips

### Metric-tile tooltips (hover + keyboard focus)
Each stat tile is hoverable (`cursor: help`, dotted underline under the label)
and shows a small cream plate popover (ebony top-rule, Playfair title, a
plain-language line, then a mono "how it's calculated" line). Opens on
`:hover` and `:focus-within` for accessibility.

Copy (grounded in `wood_league.wiki/analysis-math.md`):

- **Accuracy** — "How closely this player's moves matched the engine's best, on a
  0–100% scale." · *calc:* "From per-move winning-chance drops; one big mistake
  hurts more than several small ones."
- **ACPL** — "Average centipawn loss — the typical evaluation given up per move
  versus the engine's best (100 = one pawn)." · *calc:* "Average of every move's
  centipawn loss. Lower is better; 0 = engine-perfect."
- **Avg Win% drop** — "The average percentage-point fall in this player's winning
  chances per move." · *calc:* "Engine eval → win-probability curve, then
  averaged. Lower is better."

LC0-only copy (for the LC0 card step):
- **Accuracy** — "How closely this player matched LC0's preferred moves, on a
  0–100% scale." · *calc:* "Measured from LC0's rating-adjusted win/draw/loss
  probabilities, not centipawns."
- **Avg Δμ** — "Average drop in rating-adjusted expected score per move (μ runs
  0–1, win = 1)." · *calc:* "LC0's main severity measure; adjusted for both
  players' ratings. Lower is better."

### Quality-bar legend tooltip (hover + focus)
Hovering the bar (or its "— what's this?" affordance) opens a cream plate
popover keyed by **color swatch → glyph → Band → plain meaning**, listing every
band the engine can emit, with thresholds from `analysis-math.md`:

- `!!` Brilliant — near-best, a bold sacrifice in a tense spot
- Best — matches the engine's top move
- `!` Great — near-best and clearly beats the runner-up
- Excellent — only a little given up (10–50cp)
- `?!` Inaccuracy — small edge lost (50–100cp)
- `?` Mistake — meaningful edge lost (100–300cp)
- `??` Blunder — serious error (300cp+)

## Implementation notes

- Keep card CSS in the partial's `<style>` block (matches the current pattern in
  `_card_sf.html` / `_card_lc0.html`); all colors via the existing `:root` tokens
  in `main.css` — **no new color tokens unless a band needs one**.
- Preserve all existing data hooks, context variables, `aria-label`s, and the
  `{% if count %}` segment guards; this is a **styling/markup** change, not a data
  change.
- After all template edits for an element, rebuild Tailwind as the **last step**
  via `services/app/bin/build_tailwind.sh` (Node 22) so the css-staleness CI gate
  passes, even though the change is mostly custom CSS.

## Move Analysis section — locked design

Files: `services/app/templates/games/analysis.html` (the `Move Analysis`
`pg-section`), `partials/_move_chips.html` + `static/games/moveChips.css`,
`_board_partial.html`, `_engine_line_partial.html`, and
`static/games/engineLines.js`. Shared chip/plate styling moves into
`main.css` (@layer components) alongside the card styles.

### Layout — full-width chips strip, then two aligned board plates
The section keeps its `pg-head` (`MOVE ANALYSIS`). Below it, in order:

1. A **full-width `THIS MOVE` plate** holding the move-quality chips.
2. A **two-column grid (`1fr 1fr`)** of board plates — **POSITION** (left, the
   game board) and **ENGINE LINE** (right, the arrow-continuation explorer) —
   whose **boards line up row-for-row**.

This maps cleanly onto the current DOM: `#move-chips` already renders as a
full-width strip *above* `#boards-container`, so the change is mostly wrapping
existing pieces in Du Bois plates, not restructuring. Each plate is the same
frame as the SF/LC0 cards: `var(--color-cream)`, `border-radius: 0`,
`border-top: 3px solid var(--color-ebony)`, thin
`color-mix(... var(--color-peat) 22% ...)` enclosing border, **no shadow**.

### `THIS MOVE` chips plate (full width)
- **Header:** Playfair uppercase forest title `THIS MOVE` with a hairline bottom
  rule; right side a mono context label (e.g. `ply 24 · magnus to move`).
- **Chips:** one wrapping row. Each tag is a **form-2 tile** — `var(--color-parchment)`
  background, sharp corners, thin peat border, and a **`2.5px` band-colored top
  rule** (the same idiom as the card stat tiles). This replaces the old rounded
  pills (`border-radius: 999px`) in `moveChips.css`.
- **Engine source:** a tiny mono uppercase `SF` / `LC0` prefix label (in
  `var(--color-rust)`) precedes each engine's chips, inline in the same row.
- **Draw-character chips** (LC0: Simplification · Risky · Losing Blunder ·
  Missed Win) stay **subordinate** — `~50%` opacity and a thinner (`1.5px`) top
  rule — and keep a leading `~` marker (they are outside the conventional
  `!?` glyph map).
- Band palette and conventional glyphs (`??` blunder, `?` mistake, `?!`
  inaccuracy, `!` great, `!!` brilliant; Best/Excellent/Good glyph-less) per the
  table above. Preserve existing `move-annotation-*` classes, `title` tooltips,
  and the `kind` (`sf` / `lc0_base` / `lc0_draw`) hooks.

### POSITION plate (left)
- **Header:** Playfair `POSITION` + the existing `ⓘ` run-info tooltip on the right.
- Below: the existing board markup — ebony `side · name` player-label bars (top
  `♚ Black …`, bottom `♔ White …`), the board, then the controls row (transport
  buttons, gold slider, mono ply label).
- **Token cleanup:** replace the partial's hardcoded hex (`#1A1A1A`, `#8B3A2A`,
  `#D4C4A0`, `#D4A843`, arrow `#A8781B`/`#35586F`, etc.) with the matching
  `:root` tokens (`--color-ebony`, `--color-rust`, `--color-gold`,
  `--color-tobacco`, `--color-denim`, …). Keep the current visual idiom — this is
  a token swap, not a redesign of the board internals.

### ENGINE LINE plate (right)
- **Header:** Playfair `ENGINE LINE` + a mono context label on the right
  (`—` when idle; arrow context when active).
- **Empty state:** the plate **stretches to match the POSITION plate's height**
  with a vertically-centered mono prompt: *"Click an engine arrow on the board
  to explore the continuation."*
- **Populated (after an arrow click):** to keep the engine board aligned with the
  game board, the plate mirrors the POSITION plate's vertical rhythm —
  a **context bar** (height-matched to the top player-label, e.g.
  `↳ after 24.♘f5 · +1.4`), the **board**, a **bottom spacer**
  (height-matched to the bottom player-label), the controls row, then a mono
  `CONTINUATION` micro-label and the move list. This extends the existing
  `engine-line-player-spacer` / `_applyEngineLineBorderStyles` alignment
  mechanism in `engineLines.js` (which currently aligns the bottom edge) to also
  cover the top via the context bar.
- **Continuation move list — inline flowing line (not a table):** moves render as
  a single wrapping EB-Garamond line (`24.♘f5 ♝xf5 25.♖xe8 …`), mono move
  numbers in `var(--color-peat)`, each SAN clickable to jump (preserve the
  per-move ply hook + jump handler), and the **active move boxed** with a gold
  wash (`color-mix(... var(--color-gold) 35% ...)`) + `2px` forest underline.
  This requires rewriting `renderContinuationTable` / `renderContinuationSelection`
  in `engineLines.js` to emit inline spans instead of `<table>` rows — so this
  element is **not pure-markup** like the SF/LC0 cards were.

### Scope / build notes for this element
- The shared **PGN panel keeps its own treatment** (a later element): the inline
  continuation diverges from the `.move-list-*` table the PGN panel reuses, so
  PGN is no longer settled by this step.
- Preserve all data hooks, `aria-label`s, HTMX wiring, and the `{% if %}` guards;
  bandit-scan any edited `.py` (none expected — this is templates/CSS/JS).
- After all template/CSS edits, rebuild Tailwind as the **last step** via
  `services/app/bin/build_tailwind.sh` under **Node 22** and commit
  `tailwind.css`, or the css-staleness CI gate fails (see
  `project_tailwind_node22`).

## Remaining elements (incremental, after SF + LC0 cards + Move Analysis)

To be designed/locked in subsequent passes, each reviewed live:
1. Win% / SF-cp / LC0-WDL charts.
2. PGN move-list panel (own treatment — see note above).
3. Page hero + "re-analysis required" empty state.
