# Game-Analysis: charts in cards + perspective flip

Date: 2026-05-27
Status: Draft, awaiting user review

## Summary

Relocate the per-engine charts on the Game Analysis page into their owning
stat cards, add a perspective-flip control to the Position card, decorate the
LC0 chart with a per-ply classification strip, and retire the redundant
Win-for-White chart and the LC0 "Avg winning chances for whole game" strip.

## Motivation

Today the page renders three full-width chart sections below the boards
(`winpct`, `sf-cp`, `lc0-wdl`). Each engine's stats and its chart live in
different parts of the page, and `winpct` duplicates information now carried
by the LC0 WDL view. Bringing each chart inside its card consolidates the
engine's signals, frees vertical space, and removes a redundant view.

The flip-perspective control is the affordance that's currently missing for
state that `plySync.js` already manages: `setPerspective(...)` exists and is
subscribed by the board partial and both charts, but there is no UI to drive
it from the page.

## Scope

In scope:

1. Remove LC0 card's "Avg. Winning Chances for Whole Game" strip.
2. Mount the existing SF centipawn chart at the bottom of the SF card.
3. Mount the existing LC0 WDL chart at the bottom of the LC0 card.
4. Add a per-ply classification strip along the bottom of the LC0 chart.
5. Add a `⇅ Flip` button to the Position-card header that toggles
   `WoodLeagueAnalysis` perspective state; board and charts already react.
6. Retire the Win-for-White chart (template, view, URL, JS, page slot).

Out of scope:

- Restyling the SF chart's classification colours or layout beyond what's
  required to fit inside the card frame.
- Mobile-specific reflow — the existing `repeat(auto-fit, minmax(280px, 1fr))`
  grid handles small viewports and Plotly is already responsive.
- Persisting the "last-used perspective" outside the URL — the `orientation`
  query param already round-trips perspective.

## Design

### LC0 card — remove whole-game GWC strip

File: `services/app/templates/games/partials/_card_lc0.html`.

Delete the block at lines 32–52 (`{% with gw=wdl.white %} ... {% endwith %}`).
That removes the `Avg. Winning Chances for Whole Game` heading, the
white/draw/black flex bar, and its legend popup.

`services/app/games/cards.py::build_lc0_card_context` keeps producing the
`wdl` key for now. Removing the producer is left as a follow-up after
confirming no other template or test consumes it.

Tests that assert on the GWC strip's presence are updated to assert its
absence.

### SF card — chart at bottom

File: `services/app/templates/games/partials/_card_sf.html`.

Append a chart slot at the bottom of the card:

```html
<div hx-get="{% url 'games:partial_chart_sf_cp' game.slug %}"
     hx-trigger="load"
     hx-swap="innerHTML">Loading chart…</div>
```

The exact URL name is verified against `services/app/games/urls.py` during
implementation.

`_chart_sf_cp.html` keeps its current `<section class="wc-chart">` wrapper.
A small CSS pass during implementation may flush the section's margins so
it reads as a sub-block of the card (mirroring `card-qwrap` rhythm); no
functional change.

`sfCp.js` is unchanged.

### LC0 card — chart at bottom + classification strip

File: `services/app/templates/games/partials/_card_lc0.html`.

Append the analogous chart slot at the card bottom (parallel to the SF
card).

The LC0 chart payload is extended:

- `services/app/games/views.py` (the `_chart_lc0_wdl/` view) and any
  helper in `services/app/games/services.py` that builds the payload now
  emit, per ply, a `classification` field (string, one of
  `best | excellent | good | inaccuracy | mistake | blunder` or empty
  when the ply has no LC0 classification).
- The source is the per-move LC0 rows already loaded by the card view; this
  is a projection, not a new DB read.

`services/app/static/games/charts/lc0Wdl.js` renders a sibling element
beneath the Plotly div, inside the same partial:

```html
<div id="lc0-wdl-chart" ...></div>
<div id="lc0-wdl-cls-strip" class="lc0-wdl-cls-strip" role="list"></div>
```

The strip is a flex row, one cell per ply spanning the chart's full
horizontal extent. Each cell:

- Carries the appropriate `move-annotation-<cls>` class so its background
  colour resolves from the shared `main.css` palette already used by the
  card's move-quality bars.
- Has a `title` of `Ply N · <SAN> · <human classification>`.
- On click calls `WoodLeagueAnalysis.setPly(ply)`.

The strip is keyed by ply, which is a time index; flipping perspective
does not reorder cells. The Plotly chart re-renders its WDL bands on
perspective change, but the strip's contents are perspective-independent.

### Flip-perspective button

File: `services/app/templates/games/analysis.html` — the Position-card
header (around line 189).

Add a button immediately after the existing arrow-toggle group:

```html
<button type="button" id="board-flip-btn"
        class="arrow-tg arrow-tg--flip"
        aria-label="Flip board perspective">⇅ Flip</button>
```

Click handler: toggle perspective via the shared state helper.

`services/app/static/games/plySync.js` gains a `togglePerspective()`
convenience method:

```js
togglePerspective: function () {
  this.setPerspective(_perspective === "white" ? "black" : "white");
}
```

The button binds to it on load (small inline script in `analysis.html`,
co-located with the existing `WoodLeagueAnalysis.initFromUrl` block).

Downstream behaviour is already wired:

- `board_partial` is re-fetched via HTMX with the new `?orientation=` (verify
  during implementation; if missing, add the subscription).
- SF and LC0 charts re-render via their existing `subscribe` callbacks.

### Retire Win-for-White

Delete:

- `services/app/templates/games/partials/_chart_winpct.html`
- `services/app/static/games/charts/winpct.js`
- The Django view and URL pair for `/_partials/games/<slug>/charts/winpct/`
  (in `services/app/games/views.py` and `services/app/games/urls.py`).
- The `<div hx-get="...charts/winpct/">` slot in
  `services/app/templates/games/analysis.html`.
- Any winpct-specific helpers in `services/app/games/services.py` or
  `services/app/games/cards.py` that no other consumer references.
- Test files that exclusively cover the winpct payload.

## Testing

- Django template tests for `_card_sf.html` and `_card_lc0.html`:
  - Assert the chart-slot element with its `hx-get` URL is rendered.
  - Assert the LC0 card no longer contains the GWC text/markup.
- Payload test for the LC0 WDL chart endpoint: assert every ply entry
  carries a `classification` field (possibly empty string) of the expected
  type.
- View test for the Position-card header: assert the `#board-flip-btn`
  element is rendered with the expected ARIA label.
- Removal regression: deleted winpct view, URL, JS, and template paths are
  unreachable / 404 (a tiny URL-resolution test is enough).

No JS unit tests; the chart JS files are well-isolated and existing manual
review covers them.

## Risks / Notes

- The LC0 chart payload extension is additive; existing consumers
  (`lc0Wdl.js`) ignore unknown fields, so a stale browser session won't
  break if cached. Tests cover the new field's presence.
- Card width can be ~280px on the narrowest viewport (per the existing
  `auto-fit` grid). The relocated charts render responsively and remain
  readable, but a dense game (>150 plies) may compress the classification
  strip cells to ~1–2px each. Acceptable — the strip is a
  "is-there-a-blunder-cluster" signal at the small end, with detailed
  inspection on hover.
- Retiring `winpct` removes one user-facing visualization. The LC0 WDL
  chart now serves the same purpose with strictly more information; we
  judge the loss redundant.

## Acceptance

- Game Analysis page renders with SF chart inside SF card, LC0 chart with
  classification strip inside LC0 card, no Win-for-White chart, no
  "Avg. Winning Chances for Whole Game" strip.
- `⇅ Flip` in the Position-card header flips the board and both charts;
  ply marker persists; URL `orientation` updates.
- Click a bar in the SF chart, an area in the LC0 chart, or a cell in the
  classification strip — board, charts, and chips all jump to that ply.
- All existing analysis tests pass; new tests above pass.
