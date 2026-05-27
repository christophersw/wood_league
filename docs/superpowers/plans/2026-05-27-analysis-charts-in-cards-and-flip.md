# Game-Analysis: charts in cards + perspective flip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate per-engine charts into their stat cards, add a perspective-flip button, decorate the LC0 chart with a per-ply classification strip, and retire the redundant Win-for-White chart and the LC0 whole-game GWC block.

**Architecture:** Each card template gains an HTMX slot at the bottom that loads the existing chart partial (no duplicate render path). `plySync.js` gains a `togglePerspective()` helper; the page-level `WoodLeagueAnalysis.subscribe` callback in `analysis.html` re-fetches `board_partial` on perspective change. LC0 chart payload is extended with a per-ply `classification`; `lc0Wdl.js` renders a sibling strip below the Plotly div using the existing `move-annotation-<cls>` palette. Win-for-White (template, view, URL, JS, payload, page slot, tests) is deleted.

**Tech Stack:** Django templates, HTMX, Plotly, vanilla JS, Tailwind v4. Tests via pytest + django-test. Quality gate pipeline (ruff → bandit/semgrep → radon/xenon → mypy → pytest+cov) per project standard.

**Issue:** https://github.com/christophersw/wood_league/issues/216
**Spec:** `docs/superpowers/specs/2026-05-27-analysis-charts-in-cards-and-flip-design.md`

---

## Repo orientation (reference for every task)

- Run from repo root: `source .venv/bin/activate`
- Tests: `cd services/app && pytest <path> -v`
- Tailwind rebuild (LAST step, before commit if any template/CSS changed): `services/app/bin/build_tailwind.sh` — use Node 22.
- `bandit -ll <file>` on every edited `.py`. Fix Medium/High findings.
- Per CLAUDE.md: prefer `mcp__vexp__run_pipeline` for navigation over grep/glob.
- Library docs (Plotly, Django, HTMX): use `mcp__plugin_context7_context7__resolve-library-id` + `query-docs`.

## File map

**Create:**
- (none — the chart partials and JS already exist)

**Modify:**
- `services/app/games/chart_data.py` — add `classification` to `lc0_wdl_payload`; delete `winpct_payload`.
- `services/app/games/views.py` — delete `chart_winpct_partial`.
- `services/app/games/partial_urls.py` — delete `games_chart_winpct_partial` route.
- `services/app/templates/games/partials/_card_sf.html` — append SF chart slot.
- `services/app/templates/games/partials/_card_lc0.html` — delete GWC strip; append LC0 chart slot.
- `services/app/templates/games/partials/_chart_lc0_wdl.html` — add classification strip container.
- `services/app/static/games/charts/lc0Wdl.js` — render classification strip; wire click → setPly.
- `services/app/static/games/plySync.js` — add `togglePerspective()`.
- `services/app/templates/games/analysis.html` — add `⇅ Flip` button; remove winpct/sf-cp/lc0-wdl bottom slots; wire perspective-change → board re-fetch.
- `services/app/static/css/main.css` — `.lc0-wdl-cls-strip` and flip-button styles.
- `services/app/static/css/tailwind.css` — rebuilt artifact (do NOT hand-edit; run `bin/build_tailwind.sh`).

**Delete:**
- `services/app/templates/games/partials/_chart_winpct.html`
- `services/app/static/games/charts/winpct.js`
- Any test file exclusively covering winpct.

**Test files (modify):**
- `services/app/games/tests/test_chart_data.py` (add classification assertion; drop winpct tests).
- `services/app/games/tests/test_partial_routes.py` (drop `games_chart_winpct_partial`).
- `services/app/games/tests/test_view_game_analysis_shell.py` (drop `charts/winpct`, assert flip button).
- `services/app/games/tests/test_cards_lc0.py` (assert GWC strip absent; assert chart slot present).
- `services/app/games/tests/test_cards_sf.py` (assert chart slot present).

---

## Task 0: Set up worktree

**Files:** none yet.

- [ ] **Step 1: Create worktree**

```bash
cd /Users/christopherwebster/Projects/wood_league
git fetch origin main
git worktree add -b issue/216-charts-in-cards-and-flip .claude/worktrees/issue+216-charts-in-cards-and-flip origin/main
```

- [ ] **Step 2: Bootstrap worktree env**

```bash
cd .claude/worktrees/issue+216-charts-in-cards-and-flip
# Reuse the repo-root venv (per memory: project_venv)
# From services/app: source ../../.venv/bin/activate
# Symlink .env if needed (memory: project_run_app_locally_worktree).
ls services/app/.env || echo "Create or symlink services/app/.env before running the app"
```

- [ ] **Step 3: Confirm clean test baseline**

```bash
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
cd services/app
pytest games/tests -x -q
```

Expected: all tests pass.

---

## Task 1: Extend `lc0_wdl_payload` with per-ply `classification`

**Files:**
- Modify: `services/app/games/chart_data.py:55-65`
- Test: `services/app/games/tests/test_chart_data.py`

- [ ] **Step 1: Skeleton-read the existing test file**

```bash
# Prefer get_skeleton over Read per CLAUDE.md
# Tool: mcp__vexp__get_skeleton(files=["services/app/games/tests/test_chart_data.py"], detail="detailed")
```

If `test_chart_data.py` does not exist, create it (Step 2 will write the test).

- [ ] **Step 2: Write the failing test**

Append to `services/app/games/tests/test_chart_data.py`:

```python
def test_lc0_wdl_payload_includes_classification(lc0_data_with_classifications):
    """Each ply entry carries a `classification` string."""
    from games.chart_data import lc0_wdl_payload
    payload = lc0_wdl_payload(lc0_data_with_classifications)
    assert payload, "fixture must produce at least one row"
    for row in payload:
        assert "classification" in row
        assert isinstance(row["classification"], str)
        # Allowed values: empty string or one of the LC0 base-severity classes
        assert row["classification"] in {
            "", "best", "excellent", "good", "inaccuracy", "mistake", "blunder",
        }
```

You will need a fixture `lc0_data_with_classifications` that builds a minimal `GameAnalysisDataV2` with at least one classified `lc0_moves` row. Follow the pattern used in the existing fixtures in `services/app/games/tests/conftest.py` (find with `mcp__vexp__run_pipeline({task: "GameAnalysisDataV2 fixture lc0_moves classification"})`).

- [ ] **Step 3: Run test — expect failure**

```bash
cd services/app
pytest games/tests/test_chart_data.py::test_lc0_wdl_payload_includes_classification -v
```

Expected: FAIL (KeyError on `"classification"`).

- [ ] **Step 4: Implement**

Edit `services/app/games/chart_data.py` `lc0_wdl_payload`:

```python
def lc0_wdl_payload(data: GameAnalysisDataV2) -> list[dict]:
    """Build the LC0 WDL chart payload.

    Each entry carries the White-frame WDL triple plus the per-move
    base-severity classification used by the bottom-of-chart classification
    strip in lc0Wdl.js.

    Params:
        data: GameAnalysisDataV2 — the analysed game.

    Returns:
        list[dict]: One dict per analysed move, keys ``ply``, ``wdl_win``,
        ``wdl_draw``, ``wdl_loss``, ``san``, ``classification``.
    """
    return [
        {
            "ply": m.ply,
            "wdl_win": m.wdl_win_adj,
            "wdl_draw": m.wdl_draw_adj,
            "wdl_loss": m.wdl_loss_adj,
            "san": m.san,
            "classification": (getattr(m, "classification", "") or "").lower(),
        }
        for m in data.lc0_moves
    ]
```

- [ ] **Step 5: Run test — expect pass**

```bash
pytest games/tests/test_chart_data.py::test_lc0_wdl_payload_includes_classification -v
```

Expected: PASS.

- [ ] **Step 6: Bandit**

```bash
bandit -ll services/app/games/chart_data.py
```

Expected: no Medium/High findings.

- [ ] **Step 7: Commit**

```bash
git add services/app/games/chart_data.py services/app/games/tests/test_chart_data.py
git commit -m "feat(#216): lc0_wdl_payload emits per-ply classification"
```

---

## Task 2: Remove LC0 "Avg. Winning Chances for Whole Game" strip

**Files:**
- Modify: `services/app/templates/games/partials/_card_lc0.html:32-52`
- Test: `services/app/games/tests/test_cards_lc0.py`

- [ ] **Step 1: Write the failing test (absence assertion)**

Add to `services/app/games/tests/test_cards_lc0.py`:

```python
def test_lc0_card_has_no_whole_game_gwc_strip(client, analyzed_game):
    """The whole-game "Avg. Winning Chances" strip is retired (#216)."""
    resp = client.get(f"/_partials/games/{analyzed_game.slug}/cards/lc0/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Avg. Winning Chances for Whole Game" not in body
    assert "card-gwc" not in body
```

- [ ] **Step 2: Run test — expect failure**

```bash
pytest games/tests/test_cards_lc0.py::test_lc0_card_has_no_whole_game_gwc_strip -v
```

Expected: FAIL (string present).

- [ ] **Step 3: Delete the GWC block**

Open `services/app/templates/games/partials/_card_lc0.html` and delete lines 32–52 (the entire `{# Whole-game average winning chances ... #} {% with gw=wdl.white %} ... {% endwith %}` block including the `{% if gw.win or gw.draw or gw.loss %}` branch and its `{% endif %} {% endwith %}` closers).

- [ ] **Step 4: Run test — expect pass**

```bash
pytest games/tests/test_cards_lc0.py::test_lc0_card_has_no_whole_game_gwc_strip -v
```

Expected: PASS.

- [ ] **Step 5: Run the rest of the LC0 card tests — no regressions**

```bash
pytest games/tests/test_cards_lc0.py -v
```

Expected: any tests that previously asserted on the GWC block are updated in this step (find them, replace the positive assertion with the new negative one or delete the obsolete test).

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/games/partials/_card_lc0.html services/app/games/tests/test_cards_lc0.py
git commit -m "refactor(#216): drop LC0 whole-game GWC strip"
```

---

## Task 3: Mount SF chart slot at the bottom of SF card

**Files:**
- Modify: `services/app/templates/games/partials/_card_sf.html`
- Test: `services/app/games/tests/test_cards_sf.py`

- [ ] **Step 1: Write the failing test**

Append to `services/app/games/tests/test_cards_sf.py`:

```python
def test_sf_card_renders_chart_slot(client, analyzed_game):
    """The SF card embeds a slot that loads the SF cp chart via HTMX (#216)."""
    resp = client.get(f"/_partials/games/{analyzed_game.slug}/cards/sf/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/_partials/games/{analyzed_game.slug}/charts/sf-cp/" in body
    assert 'hx-trigger="load"' in body
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest games/tests/test_cards_sf.py::test_sf_card_renders_chart_slot -v
```

- [ ] **Step 3: Append slot to `_card_sf.html`**

Add just before the closing `</section>`:

```django
  <div class="wc-card__chart-slot"
       hx-get="{% url 'partials:games_chart_sf_cp_partial' game.slug %}"
       hx-trigger="load"
       hx-swap="innerHTML">Loading SF chart…</div>
```

The URL name comes from `services/app/games/partial_urls.py:23`. The partials app is mounted under namespace `partials` (verify via `mcp__vexp__run_pipeline({task: "partial_urls.py app_name"})`); if no namespace exists, the URL `{% url 'games_chart_sf_cp_partial' game.slug %}` is correct without prefix.

The card template currently receives `game` in its context (check via the existing `tooltip_meta` references). If it does not, also update `build_sf_card_context` in `services/app/games/cards.py` to inject `game` (slug-only is enough).

- [ ] **Step 4: Run — expect PASS**

```bash
pytest games/tests/test_cards_sf.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/partials/_card_sf.html services/app/games/tests/test_cards_sf.py services/app/games/cards.py
git commit -m "feat(#216): mount SF cp chart inside SF card"
```

---

## Task 4: Mount LC0 chart slot at the bottom of LC0 card

**Files:**
- Modify: `services/app/templates/games/partials/_card_lc0.html`
- Test: `services/app/games/tests/test_cards_lc0.py`

- [ ] **Step 1: Write the failing test**

```python
def test_lc0_card_renders_chart_slot(client, analyzed_game):
    """The LC0 card embeds a slot that loads the LC0 WDL chart via HTMX (#216)."""
    resp = client.get(f"/_partials/games/{analyzed_game.slug}/cards/lc0/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert f"/_partials/games/{analyzed_game.slug}/charts/lc0-wdl/" in body
    assert 'hx-trigger="load"' in body
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest games/tests/test_cards_lc0.py::test_lc0_card_renders_chart_slot -v
```

- [ ] **Step 3: Append slot to `_card_lc0.html`**

Just before the closing `</section>`:

```django
  <div class="wc-card__chart-slot"
       hx-get="{% url 'partials:games_chart_lc0_wdl_partial' game.slug %}"
       hx-trigger="load"
       hx-swap="innerHTML">Loading LC0 chart…</div>
```

Mirror any context-injection fix from Task 3 (`game` slug passed to `build_lc0_card_context`).

- [ ] **Step 4: Run — expect PASS**

```bash
pytest games/tests/test_cards_lc0.py -v
```

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/partials/_card_lc0.html services/app/games/tests/test_cards_lc0.py services/app/games/cards.py
git commit -m "feat(#216): mount LC0 WDL chart inside LC0 card"
```

---

## Task 5: LC0 chart — classification strip in template + JS

**Files:**
- Modify: `services/app/templates/games/partials/_chart_lc0_wdl.html`
- Modify: `services/app/static/games/charts/lc0Wdl.js`
- Modify: `services/app/static/css/main.css`

- [ ] **Step 1: Add the strip container to the partial**

Edit `_chart_lc0_wdl.html`. After the existing `<div id="lc0-wdl-chart">` add:

```django
<div id="lc0-wdl-cls-strip" class="lc0-wdl-cls-strip" role="list"
     aria-label="LC0 per-ply move quality"></div>
```

- [ ] **Step 2: Add the CSS rules**

Append to `services/app/static/css/main.css`:

```css
/* LC0 WDL classification strip — sibling to #lc0-wdl-chart, populated by lc0Wdl.js.
   Each cell uses .move-annotation-<cls> for its background, matching the
   move-quality bars in the SF/LC0 cards. */
.lc0-wdl-cls-strip { display: flex; gap: 0; height: 12px; margin: 2px 0 0; }
.lc0-wdl-cls-strip .cls-cell { flex: 1 1 0; min-width: 1px; cursor: pointer; }
.lc0-wdl-cls-strip .cls-cell:hover { outline: 1px solid var(--color-forest); outline-offset: -1px; }
```

- [ ] **Step 3: Render the strip in `lc0Wdl.js`**

Find the IIFE that ends after the Plotly `newPlot(...).then(...)` block. Inside `.then(...)`, after the existing `WoodLeagueAnalysis.subscribe(...)` registration, add the strip renderer:

```js
// Render the per-ply classification strip (#216).
var stripEl = document.getElementById("lc0-wdl-cls-strip");
if (stripEl) {
  var sanByPly = {};
  rawPayload.forEach(function (d) { sanByPly[Number(d.ply)] = d.san; });
  rawPayload.forEach(function (d) {
    var cell = document.createElement("div");
    cell.className = "cls-cell move-annotation-" + ((d.classification || "").toLowerCase() || "none");
    var ply = Number(d.ply);
    var human = (d.classification || "—").replace(/^./, function (c) { return c.toUpperCase(); });
    cell.title = "Ply " + ply + " · " + (sanByPly[ply] || "") + " · " + human;
    cell.setAttribute("role", "listitem");
    cell.addEventListener("click", function () {
      WoodLeagueAnalysis.setPly(ply);
    });
    stripEl.appendChild(cell);
  });
}
```

Note: cells with no classification get class `move-annotation-none` (no matching rule in CSS → transparent, which is the desired "unclassified" visual).

- [ ] **Step 4: Manual verification** (we don't unit-test the JS; rely on the eyeball check)

Document expected behavior in the JS file header changelog comment:

```js
//   2026-05-27 (#216): Add per-ply classification strip below the WDL area.
```

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/partials/_chart_lc0_wdl.html \
        services/app/static/games/charts/lc0Wdl.js \
        services/app/static/css/main.css
git commit -m "feat(#216): classification strip beneath LC0 WDL chart"
```

---

## Task 6: `togglePerspective()` helper on `WoodLeagueAnalysis`

**Files:**
- Modify: `services/app/static/games/plySync.js`

- [ ] **Step 1: Add the helper**

Inside the existing `window.WoodLeagueAnalysis = { ... }` object, add a new method:

```js
    /**
     * Toggle perspective between "white" and "black".
     * Convenience wrapper around setPerspective. Notifies subscribers and syncs URL.
     */
    togglePerspective: function () {
      var next = _perspective === "white" ? "black" : "white";
      this.setPerspective(next);
    },
```

Update the file header `Changelog` to add:

```
*   2026-05-27 (#216): add togglePerspective() helper.
```

- [ ] **Step 2: Commit**

```bash
git add services/app/static/games/plySync.js
git commit -m "feat(#216): plySync togglePerspective() helper"
```

---

## Task 7: `⇅ Flip` button + analysis.html wiring

**Files:**
- Modify: `services/app/templates/games/analysis.html`
- Modify: `services/app/static/css/main.css`
- Test: `services/app/games/tests/test_view_game_analysis_shell.py`

- [ ] **Step 1: Write the failing test**

```python
def test_analysis_page_has_flip_button(client, analyzed_game):
    """The Position card header renders a perspective-flip button (#216)."""
    resp = client.get(f"/games/{analyzed_game.slug}/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="board-flip-btn"' in body
    assert "Flip" in body
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest games/tests/test_view_game_analysis_shell.py::test_analysis_page_has_flip_button -v
```

- [ ] **Step 3: Add the button to `analysis.html`**

Find the Position card header (around line 189) — the `<div class="arrow-toggles" role="group" ...>` block. Immediately after that `</div>` (closes `arrow-toggles`) add:

```html
        <button type="button" id="board-flip-btn"
                class="arrow-tg arrow-tg--flip"
                aria-label="Flip board perspective"
                title="Flip board perspective"
                onclick="window.WoodLeagueAnalysis && window.WoodLeagueAnalysis.togglePerspective()">
          <span aria-hidden="true">⇅</span> Flip
        </button>
```

- [ ] **Step 4: Wire perspective-change to board re-fetch**

In `analysis.html` at the bottom block where `WoodLeagueAnalysis.subscribe(...)` is registered, extend the callback to re-fetch the board partial when perspective changes:

```js
var _lastPerspective = WoodLeagueAnalysis.getState().perspective;
WoodLeagueAnalysis.subscribe(function (state) {
  document.body.dispatchEvent(new CustomEvent("ply-change", { detail: state }));
  if (state.perspective !== _lastPerspective) {
    _lastPerspective = state.perspective;
    if (window.htmx) {
      htmx.ajax("GET",
        "/_partials/games/{{ game.slug }}/board/?orientation=" + state.perspective,
        { target: "#board-container", swap: "innerHTML" });
    }
  }
});
```

- [ ] **Step 5: Style the button**

Append to `services/app/static/css/main.css`:

```css
/* Flip-perspective button — same chip-style envelope as the .arrow-tg
   chips so it reads as a sibling control in the Position card header. */
.arrow-tg--flip {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  letter-spacing: 0.02em;
  background: transparent;
  border: 1px solid var(--color-card-border-soft);
  padding: 2px 8px;
  border-radius: 4px;
}
.arrow-tg--flip:hover { background: color-mix(in srgb, var(--color-gold) 18%, transparent); }
.arrow-tg--flip:focus-visible { outline: 2px solid var(--color-forest); outline-offset: 1px; }
```

- [ ] **Step 6: Run — expect PASS**

```bash
pytest games/tests/test_view_game_analysis_shell.py::test_analysis_page_has_flip_button -v
```

- [ ] **Step 7: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/static/css/main.css services/app/games/tests/test_view_game_analysis_shell.py
git commit -m "feat(#216): flip-perspective button in Position card header"
```

---

## Task 8: Retire Win-for-White (template, view, URL, JS, payload, page slots)

**Files:**
- Delete: `services/app/templates/games/partials/_chart_winpct.html`
- Delete: `services/app/static/games/charts/winpct.js`
- Modify: `services/app/games/chart_data.py` (remove `winpct_payload`)
- Modify: `services/app/games/views.py` (remove `chart_winpct_partial`)
- Modify: `services/app/games/partial_urls.py` (remove route)
- Modify: `services/app/templates/games/analysis.html` (remove the 3 bottom-of-page chart slots)
- Modify: `services/app/games/tests/test_partial_routes.py`
- Modify: `services/app/games/tests/test_view_game_analysis_shell.py`
- Possibly modify or delete: any `test_chart_data.py` test for `winpct_payload`.

- [ ] **Step 1: Find every reference**

```bash
mcp__vexp__run_pipeline({task: "winpct references winpct_payload chart_winpct_partial _chart_winpct.html"})
```

Or fallback:

```bash
grep -rn "winpct\|_chart_winpct\|chart_winpct_partial" services/app
```

- [ ] **Step 2: Update / remove tests**

Update `test_partial_routes.py`: remove `"games_chart_winpct_partial"` from the route list (line 26) and delete the dedicated `resp = client.get(.../charts/winpct/)` block (around line 49).

Update `test_view_game_analysis_shell.py`: remove `"charts/winpct"` from the partial fragments list (line 29).

Delete any winpct-only tests in `test_chart_data.py`.

Add a removal test:

```python
def test_winpct_route_is_gone(client, analyzed_game):
    """The winpct chart route is retired (#216)."""
    resp = client.get(f"/_partials/games/{analyzed_game.slug}/charts/winpct/")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run tests — expect failures pointing at code still referencing winpct**

```bash
pytest games/tests/test_partial_routes.py games/tests/test_view_game_analysis_shell.py -v
```

- [ ] **Step 4: Delete the artifacts**

```bash
rm services/app/templates/games/partials/_chart_winpct.html
rm services/app/static/games/charts/winpct.js
```

Edit `services/app/games/views.py`: delete the `chart_winpct_partial` function (lines 776–792 inclusive) and any `winpct_payload` import.

Edit `services/app/games/partial_urls.py`: delete the line registering `games_chart_winpct_partial` (line 22).

Edit `services/app/games/chart_data.py`: delete the `winpct_payload` function entirely.

Edit `services/app/templates/games/analysis.html`: delete the three bottom-of-page chart slot divs (the three `<div hx-get=".../charts/...">` lines in the Move Analysis section, around lines 259–261).

Also delete the `<script src="{% static 'games/charts/winpct.js' %}">` reference if present in the `{% block extra_js %}`.

- [ ] **Step 5: Run all games tests — expect PASS**

```bash
pytest games/tests -x -q
```

- [ ] **Step 6: Bandit on all edited .py files**

```bash
bandit -ll services/app/games/views.py services/app/games/partial_urls.py services/app/games/chart_data.py
```

Expected: no Medium/High findings.

- [ ] **Step 7: Commit**

```bash
git add -A services/app/games services/app/templates/games services/app/static/games
git commit -m "refactor(#216): retire Win-for-White chart (template, view, URL, JS, payload)"
```

---

## Task 9: Tailwind rebuild + CSS staleness check

**Files:**
- Modify: `services/app/static/css/tailwind.css` (artifact)

- [ ] **Step 1: Rebuild Tailwind with Node 22** (per memory: project_tailwind_node22)

```bash
cd /Users/christopherwebster/Projects/wood_league
# If you have nvm: nvm use 22
# Otherwise verify: node --version  →  v22.x
services/app/bin/build_tailwind.sh
```

- [ ] **Step 2: Verify only expected diff**

```bash
git status services/app/static/css/tailwind.css
git diff --stat services/app/static/css/tailwind.css
```

A non-empty diff is expected. If `tailwind.css` is byte-identical to main, run the rebuild again — Node major mismatch is the common cause.

- [ ] **Step 3: Commit**

```bash
git add services/app/static/css/main.css services/app/static/css/tailwind.css
git commit -m "chore(#216): rebuild tailwind after main.css additions"
```

---

## Task 10: Verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run the quality gate**

```bash
cd services/app
# Stage 1 — lint
ruff check .
# Stage 2 — security
bandit -ll -r games templates
# Stage 3 — complexity (informational)
radon cc games -nb -s -a || true
# Stage 4 — types
mypy games chart_data.py 2>/dev/null || mypy games
# Stage 5 — tests
pytest games/tests -q --cov=games --cov-report=term-missing
```

All stages must pass per memory: feedback_quality_gate.

- [ ] **Step 2: Manual UI verification**

Per memory `project_run_app_locally_worktree`, start the app from the worktree with the symlinked `.env`:

```bash
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+216-charts-in-cards-and-flip
source ../../../.venv/bin/activate
cd services/app
DEBUG=True AUTH_ENABLED=True python manage.py runserver 0.0.0.0:8000
```

Then in a browser:
- Open any analyzed game's analysis page.
- Verify: SF chart appears inside SF card; LC0 chart appears inside LC0 card; classification strip sits below LC0 chart; no Win-for-White section; no LC0 whole-game GWC strip.
- Click `⇅ Flip`: board orientation flips, both charts flip, URL `?orientation=` updates.
- Click a bar in SF chart, an area in LC0 chart, a cell in the classification strip: shared ply jumps, board updates, chips highlight.

If anything is broken, fix it and add a regression test where feasible.

---

## Task 11: PR

**Files:** none (PR only).

- [ ] **Step 1: Push branch**

```bash
git push -u origin issue/216-charts-in-cards-and-flip
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "#216 charts into engine cards + flip button + retire winpct" \
  --body "$(cat <<'EOF'
## Summary
- SF and LC0 charts now mount inside their respective stat cards.
- LC0 chart gains a per-ply classification strip beneath it.
- New \`⇅ Flip\` perspective button in the Position card header (uses existing plySync state).
- LC0 whole-game GWC strip retired.
- Win-for-White chart retired (template, view, URL, JS, payload, page slot).

Closes #216

## Test plan
- [ ] \`pytest games/tests -q --cov=games\` clean.
- [ ] Open any analyzed game: charts mounted in cards, no winpct, no LC0 GWC strip.
- [ ] Flip button toggles board + both charts; URL \`?orientation=\` updates.
- [ ] Click bar / area / classification cell → shared ply syncs everywhere.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.

---

## Self-Review

- **Spec coverage:**
  - Spec §1 (remove LC0 GWC strip) → Task 2.
  - Spec §2 (SF chart in SF card) → Task 3.
  - Spec §3 (LC0 chart in LC0 card) → Task 4.
  - Spec §4 (classification strip) → Task 1 (payload) + Task 5 (markup/JS/CSS).
  - Spec §5 (flip button) → Task 6 (helper) + Task 7 (button + wiring + style).
  - Spec §6 (retire winpct) → Task 8.
  - Spec Testing section → covered piecewise per-task.
  - Tailwind rebuild → Task 9. Verification gate → Task 10. PR → Task 11.

- **Placeholder scan:** none. All steps have either exact code or exact commands.

- **Type consistency:** `togglePerspective` defined in Task 6 is used in Task 7's onclick handler. `classification` field added in Task 1 is consumed by Task 5's JS. URL name `partials:games_chart_sf_cp_partial` used in Tasks 3 + 4 (verify namespace early; if no `app_name` in `partial_urls.py`, drop the `partials:` prefix in both places). `move-annotation-<cls>` palette consumed in Task 5 is the same set already used by the SF/LC0 cards (`best | excellent | good | inaccuracy | mistake | blunder`), defined in `main.css`.
