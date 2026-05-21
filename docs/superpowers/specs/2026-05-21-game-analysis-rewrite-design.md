# Game Analysis Page — Ground-Up Rewrite

**Date:** 2026-05-21
**Status:** Approved (brainstorm)
**Driver:** Page is broken after the #160 / #163 / #165 / #184 refactors that introduced the raw + derived analysis schema and removed `cp_equiv`. The current `analysis.html` (927 lines) inlines all chart and table rendering, the engine cards mix legacy and new fields inconsistently, board arrows are unlabeled and frequently appear to belong to the wrong ply, and the LC0 WDL chart reads mover-frame columns instead of the White-frame `wdl_*_adj` columns that were added in #159.

This is a clean break, not a patch. Legacy analysis rows that predate the new schema will be dropped from the database; affected games will surface a "Re-analyze" prompt.

---

## Goals

- Page reads exclusively from the **raw + derived** schema introduced in #161/#163, with no fallbacks to removed fields (`cp_equiv`, mover-frame WDL displays, legacy arrow fields).
- Each visual element is an **independent HTMX partial** so the shell page stays thin, partials are reusable, and reloads target only the unit that changed.
- Charts, cards, and the board show **clear labels and tooltips** that explain what is being shown and how it was computed. A reader unfamiliar with the page should not have to guess.
- Board arrows are **labeled with engine + delta** and consistently belong to the displayed ply.
- A **move-category chip row** at the top of the board surfaces both LC0 classification levels (base severity + draw character) and the SF classification.

## Non-goals

- No changes to the worker / engine output schema.
- No changes to ingestion or job orchestration.
- No new analysis quality features (no new metrics computed) — this is a presentation rewrite over an already-rich schema.
- No mobile-first redesign. Keep responsive behavior on par with today.

---

## Page shell

`services/app/templates/games/analysis.html` becomes a thin shell. It contains:

- Page hero (title, result, opening label, external links) — unchanged.
- A grid of `<div>` slots, each with `hx-get` pointing to a partial URL and `hx-trigger="load"`.
- The shared `WoodLeagueAnalysis` ply-state module is loaded once and exposed via `window`.
- Partials that depend on ply listen with `hx-trigger="ply-change from:body"` (no full reload — they re-render their internal state from the in-page `WoodLeagueAnalysis` store).
- No inline `<script>` blocks longer than the shell glue.

## Partials

Each partial gets its own URL under `/_partials/games/<slug>/...` and its own Django view in `games/views.py`. Each partial template is named `_<unit>.html` under `services/app/templates/games/partials/`.

| Partial | URL | Template | Reload on |
|---|---|---|---|
| SF stat card | `…/cards/sf/` | `partials/_card_sf.html` | initial load + after `queue_analysis` POST |
| LC0 stat card | `…/cards/lc0/` | `partials/_card_lc0.html` | initial load + after `queue_analysis` POST |
| Board | `…/board/` | `_board_partial.html` *(existing)* | flip / ply change handled in JS |
| Move-category chip row | `…/chips/?ply=<n>` | `partials/_move_chips.html` | ply change |
| Win% headline chart | `…/charts/winpct/` | `partials/_chart_winpct.html` | initial load |
| SF cp-bar chart | `…/charts/sf-cp/` | `partials/_chart_sf_cp.html` | initial load |
| LC0 WDL chart | `…/charts/lc0-wdl/` | `partials/_chart_lc0_wdl.html` | initial load |
| PGN table | `…/pgn/` | `partials/_pgn_table.html` | initial load |
| Engine-lines board | `…/engine-line/` *(existing)* | `_engine_line_partial.html` | arrow click |

Each chart partial inlines:

- A `<div id="…-chart">` placeholder.
- A `<script type="application/json" id="…-data">` payload it ships with.
- A single `<script>` block scoped to that partial that wires Plotly and subscribes to `WoodLeagueAnalysis` ply changes.

This keeps each unit self-contained: deleting a chart means deleting one partial template + view + URL.

---

## Stat cards

### SF card

| Field | Source | Label |
|---|---|---|
| Game accuracy | `GameAnalysis.white_accuracy / black_accuracy` | "Accuracy" |
| ACPL | `GameAnalysis.white_acpl / black_acpl` | "Avg centipawn loss" |
| Classification counts | `MoveAnalysis.classification`, grouped per side | stacked bar (existing palette) |
| Avg Win% drop | `MoveAnalysis.move_win_delta`, mean over the side's moves | "Avg Win% drop" |

### LC0 card

| Field | Source | Label |
|---|---|---|
| Game accuracy | `Lc0GameAnalysis.white_accuracy / black_accuracy` (#164) | "Accuracy" |
| Game-end WDL | `Lc0GameAnalysis.white_win_prob / draw_prob / loss_prob` | stacked bar |
| Base severity counts | `Lc0MoveAnalysis.base_severity`, grouped per side | stacked bar |
| Draw-character counts | `Lc0MoveAnalysis.draw_character`, grouped per side | stacked bar (second level) |
| Avg Δμ | `Lc0MoveAnalysis.delta_mu`, mean over the side's moves | "Avg expected-score drop" |

Both cards have an **ⓘ info tooltip** in the card header that reveals analysis run metadata:

- SF: engine depth, `analyzed_at`.
- LC0: `network_name`, `engine_nodes`, `contempt`, `draw_rate_reference`, `wdl_calibration_elo`, `analyzed_at`.

The tooltip uses a `<details>`/`<summary>` micro-popover (same pattern as `move-list-panel`) so it works without JS. Hover/focus shows the full block.

Cards are independent partials so a re-queue can swap just the affected card with the "Queued" state without touching anything else.

---

## Board

Mostly preserved — it already works as a partial. Changes:

### Arrow labels

Each engine arrow rendered by `_build_arrow_entries_for_engine` gets a short label drawn on the arrow head:

- Stockfish: `SF <signed pawns>` from `arrow_score_*` (e.g. `SF +0.34`, `SF −1.20`).
- LC0: `Lc0 <signed Win% Δ>` derived from the candidate's `wdl_mu` minus the played `wdl_mu` (e.g. `Lc0 +12%`, `Lc0 −8%`).
- "Best line only" mode keeps `arrow_uci_1` per visible engine.
- Existing engine-toggle and best-line filters apply.

The current ply→arrow association bug is rooted in `board_builder.py` building arrows from `MoveRow` lists that aren't always aligned. Fix is in the design but not detailed here — implementation plan will address it.

### Move-category chip row

A new strip directly above the board (between the arrow-filter fieldset and the board SVG), driven by `partials/_move_chips.html`, reloaded on ply change.

For the current ply, render up to three chips:

- **SF**: `MoveAnalysis.classification` (e.g. "Blunder", "Best").
- **LC0 base**: `Lc0MoveAnalysis.base_severity`.
- **LC0 draw character**: `Lc0MoveAnalysis.draw_character` (e.g. "Drawish", "Sharp") — second-level category.

Each chip uses the existing `move-annotation-*` color palette, with `draw_character` getting its own muted variants so it visually subordinates to the severity chip. Chips have hover tooltips that explain the label.

---

## Charts

All three charts share a header treatment: bold title, one-line subtitle, and an ⓘ tooltip that explains both **what the chart shows** and **how it was computed** (formula + data source).

### 1. Win% headline chart (new)

- One 0–100% Y axis, "Win-for-White" (flips with perspective).
- Two line traces overlaid:
  - **SF**: Lichess logistic applied to `cp_eval` → `50 + 50·tanh(0.00368208·cp)`.
  - **LC0**: `wdl_mu * 100` (already White-frame, derived from rescaled WDL).
- Click a point → `WoodLeagueAnalysis.setPly(...)`.
- Tooltip text: *"Probability that White wins from each position. Stockfish line uses the standard Lichess logistic on centipawn evaluation; LC0 line is the neural network's calibrated win expectancy. Gaps between the lines highlight positions where the two engines disagree about who is winning."*

### 2. SF cp-bar chart (rebuilt)

- Vertical bars of `cp_eval` (White-frame), clamped to ±1200; mate plotted at the cap.
- Bar color = SF `classification` for that ply (existing palette).
- Title: "Stockfish centipawn evaluation". Subtitle: "Raw engine score, White-frame, capped at ±12 pawns."
- Tooltip: *"Stockfish's raw position score in centipawns from White's perspective. Positive = White advantage. Mate scores are shown clamped at ±12 pawns. Use the Win% chart above for a probability view; this chart is the underlying engine signal."*

### 3. LC0 WDL stacked-area (rebuilt)

- Three traces stacked to 100%, **reading from the White-frame columns**: `wdl_win_adj` (bottom = "White wins"), `wdl_draw_adj` (middle), `wdl_loss_adj` (top = "Black wins"). Perspective flip swaps top/bottom labels.
- Title: "LC0 Win / Draw / Loss". Subtitle line shows network name and calibration draw rate.
- Tooltip: *"LC0's neural-network probability distribution over the three outcomes, rescaled to a calibration draw rate of <X>% (#159). Bottom band = White wins, middle = draw, top = Black wins. Reads in White-frame regardless of who is to move."*

All three charts share a single dotted-line "current ply" highlight that follows `WoodLeagueAnalysis.state.ply`.

---

## Legacy data cleanup

A **one-shot management command** drops legacy analysis rows from the DB:

- `python manage.py drop_legacy_analyses` — deletes `GameAnalysis` and `Lc0GameAnalysis` rows where any **required new derived field is null** (heuristic: `MoveAnalysis.move_win_delta` and `Lc0MoveAnalysis.wdl_win_adj`). Cascades through per-move rows.
- Dry-run by default; `--apply` to commit. Prints a count summary.

Affected games surface the existing "No analysis data found" banner, which already offers a re-queue button.

The new page does **no** legacy-field reads. If a required derived field is missing on any move, the partial renders an explicit "Re-analysis required — schema upgraded" panel rather than half-empty charts.

---

## Acceptance criteria

1. `services/app/templates/games/analysis.html` is under 200 lines, no inline Plotly or chart-building scripts.
2. Each partial in the table above has a dedicated view + URL + template, and renders on its own with no shared globals beyond `WoodLeagueAnalysis`.
3. SF and LC0 cards read **only** new schema fields. Cards include an info tooltip with the engine run metadata listed above.
4. Board arrows display engine + signed delta labels; arrows for ply `N` are always derived from the ply `N` `MoveAnalysis` / `Lc0MoveAnalysis` row.
5. Move-category chip row appears above the board, updates on ply change, and shows SF classification + LC0 `base_severity` + LC0 `draw_character` when present.
6. Three charts render: Win% headline (new), SF cp-bar (rebuilt off raw `cp_eval`), LC0 WDL stacked-area (reading `wdl_*_adj`). All three have title, subtitle, and an info tooltip explaining content and computation.
7. `drop_legacy_analyses` management command exists, dry-run-default, and is documented in the issue.
8. A re-analysis prompt is shown for games whose analysis rows lack the required derived fields.
9. Quality gate passes (ruff → bandit → radon/xenon → mypy → pytest+cov). Tests cover: each new view returns 200 with the expected fields; chip partial renders the correct chips for fixture plies; legacy-cleanup command behavior on a mixed fixture.

## Out of scope

- Engine-line continuation board (existing `_engine_line_partial.html` and `engineLines.js`) is left as-is. It already works against the new schema.
- The PGN table partial is a clean lift-and-shift of the existing inline rendering; no behavioral changes.
