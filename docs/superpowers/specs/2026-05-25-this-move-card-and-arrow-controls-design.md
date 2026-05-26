# Move Analysis — THIS MOVE Card, Arrow Controls & Delta Labels (Design)

**Date:** 2026-05-25
**Issue:** #208 (label `upgrade`, milestone v1) — game-analysis restyle, continued.
**Branch / worktree:** `issue/208-restyle-game-analysis-page` (`.claude/worktrees/issue+208-restyle-game-analysis`)
**Prior specs (this session):** `2026-05-25-game-analysis-arrow-labels-engine-context-design.md`.

## Context

Live review of the restyled Move Analysis area surfaced four refinements, scoped here as
distinct features (not bugs). They all touch the same area and share one spec; the plan may
sequence them. Design language unchanged ("Du Bois plate"): sharp corners, ebony top-rules,
cream/parchment plates, Playfair-SC titles, DM-Mono micro-labels, EB-Garamond names/numbers;
all colours via `:root` tokens in `services/app/static/css/main.css`.

Shared decision — **arrow eval labels and the card score chips are all *deltas vs the move
actually played*** (how much better/worse than what happened), mover-relative so a good move
for the side to move reads positive. SF deltas are in pawns (`+0.45`); LC0 deltas are in
win-percentage points (`+12%`). Red when the value is a loss (negative).

---

## Feature 1 — Arrow-selection controls (SF · LC0 · Best line only)

**Goal:** add the three toggle controls the board JS already expects but that were never
rendered.

- **Placement:** the POSITION plate header in `analysis.html` (`.wc-card.position-plate`
  `<header class="wc-card__head">`), to the right of the "Position" title / ⓘ.
- **Markup:** three checkbox-backed toggles with the IDs the board JS reads
  (`board-sf-toggle`, `board-lc0-toggle`, `board-best-line-toggle`). Each is a `<label>`
  wrapping a visually-hidden `<input type="checkbox">` plus the chip face, so
  `getArrowVisibilityState()` keeps reading `.checked`. `onchange` calls
  `window.boardApplyArrowVisibility && window.boardApplyArrowVisibility()` (guarded — the
  board partial loads async via HTMX and defines that function).
- **Style:** sharp Du Bois toggle chips. ON = engine-colour top-rule (2.5px) + filled
  engine-colour dot (SF `--color-tobacco`, LC0 `--color-denim`), full opacity. OFF = muted
  (opacity ~.42) + dashed border + neutral peat dot. "Best line only" is a filter, not an
  engine: a small checkbox-style box with a gold (`--color-gold`) top-rule when ON. CSS lives
  in `main.css` `@layer components` (so it ships in `tailwind.css`).
- **Defaults:** SF checked, LC0 checked, Best-line-only unchecked.
- **Behaviour (already implemented in `_board_partial.html`):** `applyArrowVisibility()`
  hides arrows + their label tags by engine + tier; `bestLineOnly` keeps only tier-1. No JS
  logic change needed beyond the controls existing and calling `boardApplyArrowVisibility()`.

---

## Feature 2 — Arrow eval labels: delta vs played, both engines

**Goal:** every arrow tag shows the candidate's delta vs the move actually played. Today SF
shows an absolute eval and **LC0 shows nothing** (the label reads the row's single
`delta_mu`, which is the played move's delta, not per-candidate, and is often unset).

- **Displayed metric (both engines, mover-relative, signed):**
  - **SF:** `(candidate_cp − played_cp)` in pawns → e.g. `+0.45` / `−0.30`.
  - **LC0:** `(candidate_μ − played_μ) × 100` in win-% points → e.g. `+12%` / `−7%`,
    where μ (expected score) = `(win + draw/2) / 1000` from a WDL triple.
- **Data:**
  - SF candidate cp = `arrow_cp_{tier}` (already on `SfMoveRow`); played reference eval from
    the row's `cp_eval`. Both normalised to the mover frame (reuse `_mover_relative_score`).
  - LC0 candidate μ needs the **per-candidate WDL triples** (`wdl_win_1/2/3`,
    `wdl_draw_1/2/3`, `wdl_loss_1/2/3`) which exist on `Lc0MoveAnalysis` (model) but are
    **not** on the `Lc0MoveRow` dataclass. **Add these nine fields to `Lc0MoveRow` and
    populate them in the row loader** (`services_v2.py`). Played μ from the row's played WDL
    (`wdl_win/draw/loss`, raw mover frame) — add the raw played triple to `Lc0MoveRow` too if
    not already carried, or derive from `wdl_mu`.
- **Implementation:** in `board_builder._arrow_entries_from_row`, compute a per-candidate
  delta for each tier (SF: cp delta; LC0: μ delta) and pass it to `_arrow_label`. `_arrow_label`
  already formats a signed delta for both engines — adjust its inputs so SF also receives a
  delta rather than an absolute candidate cp. Update `test_arrow_labels.py` accordingly.
- **Missing data:** if a candidate's source value is absent, emit no label for that arrow
  (same as the current SF behaviour) — never a broken/zero placeholder.
- **Implementation note (characterize in the plan):** the exact "played move" reference eval
  and the ply/frame alignment between candidate and played values must be pinned down with
  characterization tests before changing the math — the existing `build_board_frames` loop
  aligns rows by `current_ply` and passes `is_white_move` for the mover; the plan resolves the
  precise reference (current-position eval vs next-ply played eval) and locks it with tests.

---

## Feature 3 — "This Move" promoted to a first-class card (layout B)

**Goal:** make THIS MOVE its own HTMX partial card, synced to the live ply, carrying the
move identity + quality chips + per-engine score-change chips, and structured to grow
(coaching/explanations later).

- **Card (Du Bois plate, layout B — two columns):**
  - Header: `This Move` title.
  - **Left column:** identity line `Move {n} · {king-sym} {Side} · {player name}`
    (e.g. `Move 12 · ♔ White · magnus`), then the **move-quality chips** (the existing
    `move-annotation` form-2 tiles, grouped SF / LC0 with the source prefix and the muted `~`
    LC0 draw chip).
  - **Right column:** two **score-Δ chips** — a value tile with an engine-colour cap label
    (`SF` tobacco / `LC0` denim) over the signed delta value; red when a loss:
    - **SF Δ:** the played move's signed eval swing in pawns (e.g. `−0.45`).
    - **LC0 Δ:** the played move's `delta_mu × 100` in win-% points (e.g. `−12%`).
  - The dashed "future" affordance from the mockup is illustrative only — **not** built now.
- **Start position (ply 0):** no move has been played — show a quiet state
  (`Start position — no move yet`), no chips/scores.
- **Sync (the core fix):** the card must reflect the move that produced the currently-viewed
  position. The partial re-fetches on `ply-change`, but currently sends the *initial* ply.
  Fix: drive the request off the live ply with
  `hx-vals='js:{ply: (window.WoodLeagueAnalysis && WoodLeagueAnalysis.getState().ply) || 0}'`
  on `#move-chips` (keep `hx-trigger="load, ply-change from:body"`), and drop the hard-coded
  `?ply=` and the inert `hx-include`. So every fetch carries the current ply.
- **Components:**
  - View: extend the existing chips partial view (`views.py` `chips_partial`) — keep the
    route — to also supply `move_no`, `side`, `king_sym`, `player` (name), `sf_delta_pawns`,
    and `lc0_delta_pct` for the requested ply, alongside the existing `chips` + `move_label`.
    Watch cyclomatic complexity (grade B gate) — extract a helper that assembles the
    "this move" context if the view grows past grade B.
  - Template: rebuild `partials/_move_chips.html` into the two-column card (rename allowed,
    e.g. `_this_move.html`, updating the route's `render`).
- **SF Δ source:** signed pawns swing of the played move, mover-relative (negative = the move
  worsened the side-to-move's standing). Computed from the SF eval data; the precise field
  derivation (e.g. `cp_eval` change vs a stored measure) is pinned in the plan with a test.
- **LC0 Δ source:** `Lc0MoveRow.delta_mu × 100` for that ply (already on the dataclass).

---

## Feature 4 — Move-quality chips render as form-2 tiles

**Goal:** the quality chips in the THIS MOVE card must render as the designed form-2 tiles
(sharp parchment tile, engine-colour top-rule), not raw text on a flat background.

- **Cause:** the chips currently apply only `.move-annotation-*` (which sets a flat band
  `background`) without the `.move-chip` tile rules (border, top-rule, parchment fill, mono
  font), i.e. the `.move-chip` rules in `main.css` are not reaching the browser — consistent
  with a stale compiled `tailwind.css` being served (the `.move-annotation-*` rules predate
  this work; the `.move-chip` rules are new this session).
- **Resolution:** this folds into Feature 3's card rebuild. Ensure the chip markup carries
  the `.move-chip` tile classes, the rules live in `main.css` `@layer components`, and
  **`tailwind.css` is rebuilt under Node 22** so the served artifact contains them. Verify in
  the browser (hard refresh) that a chip shows the parchment tile + engine-colour top-rule,
  not a flat-coloured raw label.

---

## Out of scope

Win%/SF-cp/LC0-WDL charts, the PGN panel, the page hero/empty-state, and any future THIS
MOVE coaching content remain for later increments.

## Testing

- **F1 (controls):** view test that the analysis page renders the three toggle inputs with
  the expected IDs and default checked states; visibility behaviour is live-reviewed (no JS
  harness).
- **F2 (arrow deltas):** `test_arrow_labels.py` — SF arrow label is the signed pawns delta vs
  played; LC0 arrow label is the signed win-% delta vs played (driven by per-candidate WDL);
  characterization tests fixing the played-move reference/frame before the math changes;
  loader test that `Lc0MoveRow` carries the per-candidate WDL fields.
- **F3 (card):** partial-route tests that the THIS MOVE partial renders the identity
  (`Move N`, side, player), the quality chips, and both score-Δ chips with the right signed
  values for a known fixture ply; a start-position (ply 0) state test; and that the request
  carries the live ply (the `hx-vals` js-ply wiring is live-reviewed).
- **F4 (chips):** covered by F3 markup assertions (chips carry `.move-chip` tile classes) +
  the Node-22 `tailwind.css` rebuild + a browser hard-refresh check.
- **Tailwind:** rebuild `tailwind.css` under Node 22 after the `main.css` additions (F1
  toggle chips) and commit it, or the css-staleness CI gate fails.
- JS/visual behaviour (toggle hiding, tag deltas on the board, ply-sync, tile look) is
  verified by live review per `project_run_app_locally_worktree`.
