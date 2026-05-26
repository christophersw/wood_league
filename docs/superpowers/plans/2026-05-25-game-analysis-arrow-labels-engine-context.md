# Game Analysis — Arrow Labels & Engine-Line Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two open Move-Analysis bugs (chips render unstyled, THIS MOVE plate misaligned) and ship the two design changes from the spec — board arrow labels become sharp parchment tags, and the engine-line board's player slots become the bot identity + search setting.

**Architecture:** Template + CSS + vanilla-JS + a little Django-view Python on the `issue/208-restyle-game-analysis-page` worktree. Item 4 is mostly *deletion* of client JS: the engine-line border rules move to server-side `.player-label` classes (mirroring the main board), and the old `engine-lines-header` strip and its text-setter go away. Tailwind v4 (`tailwind.css`) is a committed artifact compiled from `main.css` under **Node 22** — rebuilt once at the end.

**Tech Stack:** Django templates + HTMX, vanilla JS, hand-written CSS with `:root` design tokens, pytest (Django test client). Node 22 for the Tailwind build.

**Spec:** `docs/superpowers/specs/2026-05-25-game-analysis-arrow-labels-engine-context-design.md`.

**Conventions for every task:**
- Work in the worktree: `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+208-restyle-game-analysis`. Verify `git branch --show-current` is `issue/208-restyle-game-analysis-page` before committing.
- Activate the venv from repo root before pytest: `source ../../.venv/bin/activate` (venv is at the **repo root**, not `services/app`). Run pytest from `services/app`.
- Tests live in `services/app/games/tests/test_*.py` (never `games/tests.py` — it's dead).
- Run `bandit -ll <file>` on any edited `.py` before commit (none expected to be risky here).
- JS/visual behaviour has no unit harness — verify by live review per `project_run_app_locally_worktree` (run with `DEBUG=True AUTH_ENABLED=True`).
- **Do not rebuild `tailwind.css` until Task 7** (rebuild-last convention). Chips won't look styled in a live review until then — that's expected.

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `services/app/static/css/main.css` | Receives the move-chip rules (into `@layer components`, before line 1387) | 1 |
| `services/app/templates/games/partials/_move_chips.html` | Drop the `moveChips.css` `<link>` (+ unused `{% load static %}`) | 1 |
| `services/app/static/games/moveChips.css` | **Deleted** | 1 |
| `services/app/games/tests/test_partial_routes.py` | Assert the chips partial no longer links `moveChips.css` | 1 |
| `services/app/templates/games/analysis.html` | THIS MOVE alignment; remove `engine-lines-header`; idle prompt in container; `.engine-lines-idle` CSS | 2,6 |
| `services/app/games/board_builder.py` (`_arrow_label`) | Drop the `SF`/`Lc0` prefix; return eval only | 3 |
| `services/app/games/tests/test_arrow_labels.py` | Update label assertions for the prefix drop | 3 |
| `services/app/templates/games/_board_partial.html` | Arrow-label tag JS + CSS; engine-aware title; `.player-name--bot`; drop spacer CSS | 4,5 |
| `services/app/games/views.py` (`engine_line_partial`) | Emit `bot_label` + top/bottom side/sym; drop `context_label` | 5 |
| `services/app/templates/games/_engine_line_partial.html` | Real player-label divs (bot name both sides); remove header text-setter | 5 |
| `services/app/games/tests/test_engine_line_partial.py` | Replace the `context_label` test with a bot-label test | 5 |
| `services/app/static/games/engineLines.js` | Remove `_applyEngineLineBorderStyles` + header refs; toggle idle prompt | 6 |
| `services/app/static/css/tailwind.css` | Rebuilt under Node 22 (only if changed) | 7 |

---

## Task 1: Move chip CSS into main.css; drop the standalone file + link

**Files:**
- Modify: `services/app/static/css/main.css` (insert before the `@layer components` closing `}` at line 1387)
- Modify: `services/app/templates/games/partials/_move_chips.html:1-2`
- Delete: `services/app/static/games/moveChips.css`
- Test: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_partial_routes.py`:

```python
def test_chips_partial_no_longer_links_movechips_css(client, new_schema_game_factory):
    """Chip styling now ships in the global tailwind.css; the partial must not
    inject its own moveChips.css <link> (which never applied through the HTMX swap)."""
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "moveChips.css" not in body
    assert "move-chip" in body  # chips still rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_partial_routes.py::test_chips_partial_no_longer_links_movechips_css -v`
Expected: FAIL — `moveChips.css` is still in the body.

- [ ] **Step 3: Move the chip rules into main.css**

In `services/app/static/css/main.css`, insert the following **before** the closing `}` of the `@layer components` block (currently line 1387, immediately after the `.move-annotation-blunder` rule on line 1386). Two-space indentation matches the surrounding layer:

```css

  /* ── Move-quality chips (#208; moved from games/moveChips.css) ──────────────
     Sharp "form-2" tiles inside the THIS MOVE plate: parchment background with a
     band-coloured top rule. The band colour comes from the .move-annotation-*
     palette above, re-mapped here onto the chip's top border. */
  .move-chips-card__sub {
    font-family: var(--font-mono, 'DM Mono', monospace);
    font-size: 0.6rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-peat, #5C4A2A);
  }
  .move-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    align-items: center;
    min-height: 2rem;
    padding: 0.55rem 0.75rem 0.65rem;
  }
  .move-chips__empty {
    font-family: var(--font-mono, 'DM Mono', monospace);
    font-size: 0.75rem;
    color: var(--color-peat, #5C4A2A);
    opacity: 0.6;
  }
  .move-chip__source {
    font-family: var(--font-mono, 'DM Mono', monospace);
    font-size: 0.55rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-rust, #8B3A2A);
    margin-left: 0.35rem;
  }
  .move-chip__source:first-child { margin-left: 0; }
  .move-chip {
    display: inline-flex;
    align-items: center;
    padding: 0.2rem 0.6rem 0.15rem;
    border-radius: 0;
    font-family: var(--font-mono, 'DM Mono', monospace);
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    white-space: nowrap;
    cursor: default;
    color: var(--color-ebony, #1A1410);
    background: var(--color-parchment, #F5F0E8);
    border: 1px solid color-mix(in srgb, var(--color-peat) 25%, transparent);
    border-top: 2.5px solid var(--color-band, #C9B998);
  }
  .move-chip.move-annotation-brilliant  { border-top-color: var(--color-teal); }
  .move-chip.move-annotation-best       { border-top-color: var(--color-emerald); }
  .move-chip.move-annotation-great      { border-top-color: var(--color-leaf); }
  .move-chip.move-annotation-excellent  { border-top-color: var(--color-leaf); }
  .move-chip.move-annotation-good       { border-top-color: var(--color-leaf); }
  .move-chip.move-annotation-inaccuracy { border-top-color: var(--color-saffron); }
  .move-chip.move-annotation-mistake    { border-top-color: var(--color-ember); }
  .move-chip.move-annotation-blunder    { border-top-color: var(--color-vermilion-bright); }
  .move-chip.move-annotation-simplification { border-top-color: var(--color-emerald); }
  .move-chip.move-annotation-risky          { border-top-color: var(--color-saffron); }
  .move-chip.move-annotation-losing_blunder { border-top-color: var(--color-ember); }
  .move-chip.move-annotation-missed_win     { border-top-color: var(--color-vermilion-bright); }
  .move-chip[class*="move-annotation-"] { background: var(--color-parchment, #F5F0E8); }
  .move-chip--sf,
  .move-chip--lc0_base { /* primary — full weight, no modifier */ }
  .move-chip--lc0_draw {
    opacity: 0.5;
    font-weight: 600;
    font-size: 0.66rem;
    border-top-width: 1.5px;
  }
```

- [ ] **Step 4: Drop the `<link>` and unused `{% load static %}` from the partial**

In `services/app/templates/games/partials/_move_chips.html`, delete the first two lines:

```django
{% load static %}
<link rel="stylesheet" href="{% static 'games/moveChips.css' %}">
```

so the file now starts directly with `<section class="wc-card move-chips-card" …>`. (`{% load static %}` was only used for that `<link>`; nothing else in this partial uses `static`.)

- [ ] **Step 5: Delete the standalone CSS file**

```bash
git rm services/app/static/games/moveChips.css
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd services/app && pytest games/tests/test_partial_routes.py -v`
Expected: PASS (the new test plus the existing chips-partial tests).

- [ ] **Step 7: Commit**

```bash
git add services/app/static/css/main.css services/app/templates/games/partials/_move_chips.html services/app/games/tests/test_partial_routes.py
git commit -m "fix(#208): ship move-chip CSS in main.css (drop unapplied moveChips.css link)"
```

(`tailwind.css` is rebuilt in Task 7 — chips stay unstyled in a live review until then.)

---

## Task 2: Align the THIS MOVE plate with the boards grid

**Files:**
- Modify: `services/app/templates/games/analysis.html` (`#move-chips` and `#boards-container`, lines ~45-50)

No unit test (pixel alignment) — verify by live review.

- [ ] **Step 1: Constrain the chips plate to the boards-container box**

The misalignment is because `#move-chips` (a bare div holding a full-width `.wc-card`) and `#boards-container` (the `1fr 1fr` grid) don't share identical horizontal box metrics. Both are block children of the same `.pg-section`, so the fix is to ensure neither adds stray horizontal margin and both have `margin-bottom` spacing only.

In `services/app/templates/games/analysis.html`, give `#move-chips` an explicit bottom margin matching the grid's gap and confirm no left/right inset, then verify the grid keeps its existing box:

```django
  <div id="move-chips" style="margin-bottom:24px;"
       hx-get="/_partials/games/{{ game.slug }}/chips/?ply={{ initial_ply }}"
       hx-trigger="load, ply-change from:body"
       hx-include="[name='ply']" hx-swap="innerHTML"></div>

  <div id="boards-container" style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;align-items:start;">
```

- [ ] **Step 2: Live review the alignment**

Run the app (`DEBUG=True AUTH_ENABLED=True`), open a game analysis page, and confirm the THIS MOVE plate's left edge lines up with the POSITION plate's left edge and its right edge with the ENGINE LINE plate's right edge. If a residual offset remains, inspect the `.wc-card` rule in `main.css` for any `margin` and the `.pg-section` wrapper for padding; the end state is the chips `.wc-card` spanning the full grid width with no horizontal margin. (Chips themselves still look unstyled until Task 7 — judge edges, not tile styling.)

- [ ] **Step 3: Commit**

```bash
git add services/app/templates/games/analysis.html
git commit -m "fix(#208): align THIS MOVE plate edges with the boards grid"
```

---

## Task 3: Drop the engine prefix from the arrow eval label

**Files:**
- Modify: `services/app/games/board_builder.py:456-483` (`_arrow_label`)
- Test: `services/app/games/tests/test_arrow_labels.py`

The tag's engine-colour rule + text now carry the engine, so the visible label is eval-only.

- [ ] **Step 1: Update the failing tests**

Replace the two assertions in `services/app/games/tests/test_arrow_labels.py`. Change the import line and both test bodies:

```python
from games.board_builder import build_board_frames, _UNICODE_MINUS
```

```python
def test_sf_arrow_label_is_eval_only(simple_pgn_game):
    """SF arrow label is the signed pawn eval with no engine prefix."""
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=34.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=34.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == "+0.34"


def test_lc0_arrow_label_is_eval_only(simple_pgn_game):
    """LC0 arrow label is the signed Win% delta with no 'Lc0' prefix."""
    lc0 = [Lc0MoveRow(
        ply=1, san="e4", fen="", wdl_win_adj=600, wdl_draw_adj=300, wdl_loss_adj=100,
        wdl_mu=0.75, delta_mu=-0.12, delta_d=0.0,
        base_severity="best", draw_character=None, best_move="",
        arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=[], lc0_moves=lc0, orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == f"{_UNICODE_MINUS}12%"
    assert "Lc0" not in arrow["label"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && pytest games/tests/test_arrow_labels.py -v`
Expected: FAIL — current labels still read `"SF +0.34"` / `"Lc0 −12%"`.

- [ ] **Step 3: Drop the prefix in `_arrow_label`**

In `services/app/games/board_builder.py`, replace the body of `_arrow_label` (lines ~475-483) and update its docstring summary line:

```python
def _arrow_label(engine_key: str, score: float | None, delta_mu: float | None) -> str:
    """
    Build a compact eval-only label for a v2-path arrow.

    The arrow tag conveys the engine by colour, so the label is eval text with no
    engine prefix: SF shows the candidate score in pawns to two decimals
    (e.g. "+0.34" or "−0.10"); LC0 shows the Win% delta vs the played move in
    whole percentage points (e.g. "+12%" or "−7%").

    Params:
        engine_key (str):          "sf" or "lc0".
        score      (float | None): For SF: candidate cp in the mover frame.
        delta_mu   (float | None): For LC0: (candidate_mu − played_mu).

    Returns:
        Formatted label string, or "" when the required value is absent.
    """
    if engine_key == "sf" and score is not None:
        pawns = score / 100.0
        sign = "+" if pawns >= 0 else _UNICODE_MINUS
        return f"{sign}{abs(pawns):.2f}"
    if engine_key == "lc0" and delta_mu is not None:
        delta_pct = delta_mu * 100.0
        sign = "+" if delta_pct >= 0 else _UNICODE_MINUS
        return f"{sign}{abs(delta_pct):.0f}%"
    return ""
```

- [ ] **Step 4: Run tests + bandit**

Run: `cd services/app && pytest games/tests/test_arrow_labels.py -v`
Expected: PASS.
Run: `cd services/app && bandit -ll games/board_builder.py`
Expected: no Medium/High findings.

- [ ] **Step 5: Commit**

```bash
git add services/app/games/board_builder.py services/app/games/tests/test_arrow_labels.py
git commit -m "feat(#208): arrow eval label is engine-prefix-free (colour carries engine)"
```

---

## Task 4: Render the arrow label as a sharp parchment tag (JS + CSS)

**Files:**
- Modify: `services/app/templates/games/_board_partial.html` — `<style>` (lines ~63-67), title block (lines ~311-315), and the label block in `buildArrowElement` (lines ~347-371)

No unit harness — verify by live review.

- [ ] **Step 1: Replace the arrow-label CSS**

In `services/app/templates/games/_board_partial.html`, replace the current label rules (lines ~63-67):

```css
.board-arrow-label-box,
.board-arrow-label-text{pointer-events:none;}
.board-arrow-label{font-family:var(--font-mono);font-size:11px;font-weight:700;paint-order:stroke fill;stroke:rgba(255,255,255,0.85);stroke-width:3px;pointer-events:none;}
.board-arrow-label--sf{fill:var(--color-tobacco);}
.board-arrow-label--lc0{fill:var(--color-denim);}
```

with the tag styling (parchment box + engine-colour top rule + engine-colour text, no halo):

```css
.board-arrow-label-box{fill:var(--color-parchment);stroke:color-mix(in srgb,var(--color-peat) 35%,transparent);stroke-width:1;pointer-events:none;}
.board-arrow-label-rule{pointer-events:none;}
.board-arrow-label-rule--sf{fill:var(--color-tobacco);}
.board-arrow-label-rule--lc0{fill:var(--color-denim);}
.board-arrow-label{font-family:var(--font-mono);font-size:10px;font-weight:700;pointer-events:none;}
.board-arrow-label--sf{fill:var(--color-tobacco);}
.board-arrow-label--lc0{fill:var(--color-denim);}
```

- [ ] **Step 2: Make the arrow title/aria-label engine-aware**

In `buildArrowElement`, replace the title block (lines ~311-315):

```javascript
    group.setAttribute('aria-label', arrowData.title || 'Engine continuation');

    var title = document.createElementNS(SVG_NS, 'title');
    title.textContent = arrowData.title || 'Engine continuation';
    group.appendChild(title);
```

with one that names the engine (the visible prefix is gone, so keep it for hover/screen-reader):

```javascript
    var engineName = arrowData.engine === 'lc0' ? 'Leela' : 'Stockfish';
    var evalLabel = arrowData.label || arrowData.delta_text || '';
    var describe = arrowData.title || (engineName + ' line' + (evalLabel ? ' ' + evalLabel : ''));
    group.setAttribute('aria-label', describe);

    var title = document.createElementNS(SVG_NS, 'title');
    title.textContent = describe;
    group.appendChild(title);
```

- [ ] **Step 3: Replace the rotated text with a horizontal tag**

In `buildArrowElement`, replace the entire label block (lines ~347-371, from `var rawLabelText = …` through the matching closing `}`):

```javascript
    var rawLabelText = arrowData.label || arrowData.delta_text || '';
    if (rawLabelText) {
      var labelText = String(rawLabelText);
      var engineSuffix = arrowData.engine === 'lc0' ? 'lc0' : 'sf';

      // Anchor along the shaft, then push perpendicular so the tag clears the arrow.
      var ratio = 0.66;
      var anchorX = fromPoint.x + ((geometry.shaftEndX - fromPoint.x) * ratio);
      var anchorY = fromPoint.y + ((geometry.shaftEndY - fromPoint.y) * ratio);
      var dirX = geometry.shaftEndX - fromPoint.x;
      var dirY = geometry.shaftEndY - fromPoint.y;
      var dirLen = Math.sqrt((dirX * dirX) + (dirY * dirY)) || 1;
      var perpX = -dirY / dirLen;
      var perpY = dirX / dirLen;
      var tagOffset = 15;
      var tagCenterX = anchorX + (perpX * tagOffset);
      var tagCenterY = anchorY + (perpY * tagOffset);

      var tagHeight = 15;
      var tagWidth = (labelText.length * 6) + 12;
      var tagX = tagCenterX - (tagWidth / 2);
      var tagY = tagCenterY - (tagHeight / 2);

      var labelGroup = document.createElementNS(SVG_NS, 'g');
      labelGroup.setAttribute('transform', 'translate(' + tagX + ' ' + tagY + ')');

      var box = document.createElementNS(SVG_NS, 'rect');
      box.setAttribute('class', 'board-arrow-label-box');
      box.setAttribute('width', tagWidth);
      box.setAttribute('height', tagHeight);
      labelGroup.appendChild(box);

      var rule = document.createElementNS(SVG_NS, 'rect');
      rule.setAttribute('class', 'board-arrow-label-rule board-arrow-label-rule--' + engineSuffix);
      rule.setAttribute('width', tagWidth);
      rule.setAttribute('height', '2.5');
      labelGroup.appendChild(rule);

      var label = document.createElementNS(SVG_NS, 'text');
      label.setAttribute('class', 'board-arrow-label board-arrow-label--' + engineSuffix);
      label.setAttribute('x', tagWidth / 2);
      label.setAttribute('y', (tagHeight / 2) + 1.5);
      label.setAttribute('text-anchor', 'middle');
      label.setAttribute('dominant-baseline', 'middle');
      label.textContent = labelText;
      labelGroup.appendChild(label);

      group.appendChild(labelGroup);
    }
```

- [ ] **Step 4: Live review**

Run the app, open a game with engine arrows. Confirm each arrow carries a small sharp parchment tag near its head with an engine-colour top rule and matching text (tobacco for SF, denim for LC0), showing eval only (`+0.34`, `−12%`), always upright, legible over the board. Hover an arrow → the tooltip/title names the engine (e.g. "Stockfish line +0.34"). Toggle SF/LC0 and flip the board; tags track their arrows.

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/_board_partial.html
git commit -m "feat(#208): board arrow labels as sharp parchment tags with engine rule"
```

---

## Task 5: Engine-line board shows the bot as player names (view + partial)

**Files:**
- Modify: `services/app/games/views.py:447-475` (`engine_line_partial`)
- Modify: `services/app/templates/games/_engine_line_partial.html` (lines 10-12 board bars + lines 22-25 JS)
- Modify: `services/app/templates/games/_board_partial.html` (`<style>`: add `.player-name--bot`, drop `.engine-line-player-spacer`)
- Test: `services/app/games/tests/test_engine_line_partial.py`

- [ ] **Step 1: Update the failing test**

In `services/app/games/tests/test_engine_line_partial.py`, replace `test_response_contains_context_label` with bot-label tests (the factory seeds `engine_depth=20` and `engine_nodes=800`):

```python
def test_sf_engine_line_shows_bot_player_label(client, new_schema_game_factory):
    """The engine-line board labels both player slots with the SF bot + depth."""
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="sf", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("SF bot · depth 20") == 2   # top + bottom slots
    assert "engine-lines-header" not in body       # old strip removed
    assert "Best" not in body                       # old context_label gone


def test_lc0_engine_line_shows_bot_player_label(client, new_schema_game_factory):
    """The engine-line board labels both player slots with the LC0 bot + nodes."""
    game = new_schema_game_factory()
    url = _url(game, ply=0, move_uci="e2e4", engine="lc0", tier=1, orientation="white")
    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert body.count("LC0 bot · nodes 800") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && pytest games/tests/test_engine_line_partial.py -v`
Expected: FAIL — body has no `SF bot · depth 20`; `engine-lines-header` / `Best` still present via the old `context_label` path.

- [ ] **Step 3: Emit `bot_label` + sides from the view**

In `services/app/games/views.py`, in `engine_line_partial`, **delete** the `context_parts` / `context_label` block (lines ~448-453) and **keep** `analysis_ply` (still used by `_engine_row_for_request`). Then, after `flipped = params.orientation == "black"` (line ~457), build the bot label and player-slot fields, and update the render context (lines ~469-475):

```python
    flipped = params.orientation == "black"

    if params.engine == "lc0":
        nodes = data.lc0_engine_nodes
        bot_label = f"LC0 bot · nodes {nodes:,}" if nodes else "LC0 bot"
    else:
        depth = data.engine_depth
        bot_label = f"SF bot · depth {depth}" if depth else "SF bot"

    frames, san_list = _build_continuation_frames(
        board=board,
        clicked_move=clicked_move,
        flipped=flipped,
        continuation_sans=continuation_sans,
        moves_list=moves_list,
        ply=params.ply,
    )

    arrow_labels_by_ply: dict[int, list[str]] = {}
    return render(request, "games/_engine_line_partial.html", {
        "frames_json": json.dumps(frames),
        "arrow_labels_json": json.dumps(arrow_labels_by_ply),
        "san_list_json": json.dumps(san_list),
        "bot_label": bot_label,
        "top_sym": "♟" if not flipped else "♙",
        "top_side": "Black" if not flipped else "White",
        "bottom_sym": "♙" if not flipped else "♟",
        "bottom_side": "White" if not flipped else "Black",
        "total_frames": len(frames),
    })
```

(`move_row` / `continuation_sans` lines between `flipped` and `_build_continuation_frames` stay as they are — only the `context_label` lines are removed and the render dict is replaced.)

- [ ] **Step 4: Render bot player labels in the partial**

In `services/app/templates/games/_engine_line_partial.html`, replace the three board-bar lines (10-12):

```django
  <div class="engine-line-context-bar" id="engine-line-context-bar" aria-hidden="true"></div>
  <div class="board-wrap" id="engine-line-board-svg-wrap"></div>
  <div class="engine-line-player-spacer" id="engine-line-player-spacer" aria-hidden="true"></div>
```

with real player labels mirroring the main board (bot name on both sides):

```django
  <div class="player-label{% if top_side == 'White' %} player-label-no-top{% endif %}{% if top_side == 'Black' %} player-label-no-bottom{% endif %}">
    <span class="player-side">{{ top_sym }} {{ top_side }}</span>
    <span class="player-name player-name--bot">{{ bot_label }}</span>
  </div>
  <div class="board-wrap" id="engine-line-board-svg-wrap"></div>
  <div class="player-label player-label-bottom{% if bottom_side == 'White' %} player-label-no-top{% endif %}{% if bottom_side == 'Black' %} player-label-no-bottom{% endif %}">
    <span class="player-side">{{ bottom_sym }} {{ bottom_side }}</span>
    <span class="player-name player-name--bot">{{ bot_label }}</span>
  </div>
```

Then remove the now-dead header text-setter (lines 22-25) from the partial's `<script>`:

```javascript
  var engineLinesHeader = document.getElementById('engine-lines-header');
  if (engineLinesHeader) {
    engineLinesHeader.textContent = '{{ context_label|escapejs }}';
  }
```

- [ ] **Step 5: Add `.player-name--bot` CSS; drop the dead spacer rule**

In `services/app/templates/games/_board_partial.html` `<style>`, add a bot-name variant next to `.player-name` (line ~54):

```css
.player-name--bot{font-family:var(--font-mono);font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--color-forest);}
```

and delete the now-unused `.engine-line-player-spacer` rule (line ~71):

```css
.engine-line-player-spacer{border-top:1px solid var(--color-ebony);border-bottom:2.5px solid var(--color-ebony);padding:5px 4px;min-height:36px;box-sizing:border-box;}
```

- [ ] **Step 6: Run tests + bandit**

Run: `cd services/app && pytest games/tests/test_engine_line_partial.py -v`
Expected: PASS (both bot-label tests + the existing characterization tests).
Run: `cd services/app && bandit -ll games/views.py`
Expected: no Medium/High findings.

- [ ] **Step 7: Commit**

```bash
git add services/app/games/views.py services/app/templates/games/_engine_line_partial.html services/app/templates/games/_board_partial.html services/app/games/tests/test_engine_line_partial.py
git commit -m "feat(#208): engine-line board labels both sides as the bot + setting"
```

---

## Task 6: Remove the engine-lines-header strip; idle prompt + JS cleanup

**Files:**
- Modify: `services/app/templates/games/analysis.html` (`<style>` top; `engine-lines-header` + `engine-lines-container`, lines ~13-20, 67-74)
- Modify: `services/app/static/games/engineLines.js`

This is mostly deletion — the header strip and `_applyEngineLineBorderStyles` are gone; a dedicated idle-prompt element replaces the header's prompt role.

- [ ] **Step 1: Replace the header div with an idle prompt inside the shell**

In `services/app/templates/games/analysis.html`, replace the `engine-lines-header` div and the container (lines ~68-74):

```django
        <div id="engine-lines-header"
             style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:var(--color-rust);padding:5px 8px;border-top:2.5px solid var(--color-ebony);border-bottom:1px solid var(--color-ebony);min-height:31px;box-sizing:border-box;display:flex;align-items:center;font-weight:700;">
          Click an engine arrow on the board to explore the continuation.
        </div>
        <div id="engine-lines-container" style="position:relative;color:var(--color-rust);font-family:var(--font-mono);font-size:.72rem;">
          <div id="engine-lines-loading" style="display:none;">Loading…</div>
        </div>
```

with an idle prompt that is a **sibling** of the container (so the HTMX swap, which replaces the container's contents, leaves the prompt element in place to toggle):

```django
        <div id="engine-lines-idle" class="engine-lines-idle">
          Click an engine arrow on the board to explore the continuation.
        </div>
        <div id="engine-lines-container" style="position:relative;color:var(--color-rust);font-family:var(--font-mono);font-size:.72rem;">
          <div id="engine-lines-loading" style="display:none;">Loading…</div>
        </div>
```

- [ ] **Step 2: Add the idle-prompt CSS**

Add to the `<style>` block at the top of `analysis.html` (after line 19):

```css
.engine-lines-idle { display:flex; align-items:center; justify-content:center; text-align:center; min-height:120px; padding:0 16px; line-height:1.5; border-top:2.5px solid var(--color-ebony); font-family:var(--font-mono); font-size:.72rem; color:var(--color-peat); }
```

- [ ] **Step 3: Remove `header` from `_getEngineLineElements`**

In `services/app/static/games/engineLines.js`, drop the `header` entry (lines ~94-100):

```javascript
  function _getEngineLineElements() {
    return {
      container: document.getElementById('engine-lines-container'),
      loading: document.getElementById('engine-lines-loading'),
    };
  }
```

- [ ] **Step 4: Delete `_applyEngineLineBorderStyles` and its call sites**

Delete the whole `_applyEngineLineBorderStyles` function (lines ~114-141). Then remove its callers:

- In `_clearEngineLineBoard` (lines ~233-246), remove the header reset and the border-style call, and **show the idle prompt** instead:

```javascript
    if (elements.container) {
      elements.container.style.opacity = '1';
      elements.container.innerHTML = '';
    }
    var idle = document.getElementById('engine-lines-idle');
    if (idle) {
      idle.style.display = '';
    }
    if (continuationElements.moves) {
      continuationElements.moves.innerHTML = '';
    }
    if (continuationElements.panel) {
      continuationElements.panel.style.display = 'none';
    }
    if (window.WoodLeagueMovePanels && typeof window.WoodLeagueMovePanels.sync === 'function') {
      window.WoodLeagueMovePanels.sync();
    }

    _setEngineLineControlsEnabled(false);
    _notifyEngineLines();
```

(That replaces the old block that set `elements.header.textContent` and called `_applyEngineLineBorderStyles()`.)

- Remove `applyBorderStyles` from the public API object (lines ~362-367):

```javascript
    /**
     * Clear the current continuation and reset the Engine Lines panel.
     */
    clearBoard: function () {
      _clearEngineLineBoard();
    },
  };
```

(i.e. delete the `applyBorderStyles` method and its doc comment; `clearBoard` becomes the last method before the closing `};`.)

- In the perspective-change handler (lines ~408-410), remove the `_applyEngineLineBorderStyles();` line so the block starts directly with the `var currentEngineLinePly = …`.

- Remove the module-init call `_applyEngineLineBorderStyles();` (line ~432), leaving `_setEngineLineControlsEnabled(false);`.

- In `setupEngineLineBoard`, remove the border-style call (lines ~470-472):

```javascript
  // Inform EngineLines of total ply count
  window.WoodLeagueEngineLines.setTotalPlies(totalFrames - 1);
```

(delete the `if (window.WoodLeagueEngineLines.applyBorderStyles) { … }` block that followed).

- [ ] **Step 5: Hide the idle prompt when a line loads**

In the `htmx:afterSwap` handler for engine-line requests (lines ~375-379), hide the idle prompt after a successful swap:

```javascript
    document.body.addEventListener('htmx:afterSwap', function (evt) {
      if (_isEngineLinesRequest(evt)) {
        _setEngineLineRequestState(false, '');
        var idle = document.getElementById('engine-lines-idle');
        if (idle) {
          idle.style.display = 'none';
        }
      }
    });
```

- [ ] **Step 6: Grep for stale references**

Run: `cd services/app && grep -rn "engine-lines-header\|engine-line-context-bar\|engine-line-player-spacer\|_applyEngineLineBorderStyles\|applyBorderStyles\|context_label" templates/games static/games games/views.py`
Expected: no matches (all removed).

- [ ] **Step 7: Live review**

Run the app, open a game analysis page:
- Idle: ENGINE LINE plate shows the centred prompt; header span is a quiet `—`; controls hidden.
- Click an arrow: the prompt disappears, the engine board mounts with **both** player labels reading `SF bot · depth N` (or `LC0 bot · nodes N`), borders/sides matching the main board.
- Flip the board: the engine line reloads, sides/border rules swap correctly.
- Step the main board to a different ply (deselect): the engine board clears and the idle prompt returns.

- [ ] **Step 8: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/static/games/engineLines.js
git commit -m "refactor(#208): drop engine-lines-header; idle prompt + remove border JS"
```

---

## Task 7: Tailwind rebuild + full verification

**Files:**
- Possibly: `services/app/static/css/tailwind.css` (only if regenerated)

- [ ] **Step 1: Rebuild Tailwind under Node 22**

The only `main.css` change is the chip block (Task 1); template changes added custom classes (not Tailwind utilities), so the artifact may or may not change. Rebuild and diff under Node 22 (byte output differs across Node majors — CI uses Node 22):

```bash
cd services/app
PATH="$(npx node@22 -e 'process.stdout.write(require("path").dirname(process.execPath))'):$PATH" bin/build_tailwind.sh
git diff --stat static/css/tailwind.css
```

- [ ] **Step 2: Commit the artifact only if it changed**

If `git diff --stat` shows a change:

```bash
git add services/app/static/css/tailwind.css
git commit -m "build(#208): rebuild tailwind.css for move-chip styles"
```

If no change, skip.

- [ ] **Step 3: Run the full relevant test suite**

```bash
cd services/app && pytest games/tests/test_partial_routes.py games/tests/test_arrow_labels.py games/tests/test_engine_line_partial.py games/tests/test_chip_data.py games/tests/test_view_game_analysis_shell.py -v
```

Expected: all PASS.

- [ ] **Step 4: Final live review of the whole increment**

Open a game analysis page and confirm against the spec:
- THIS MOVE chips are sharp parchment tiles with band-coloured top rules (now that `tailwind.css` is rebuilt), source prefixes present, draw chip muted — and the plate's edges line up with the boards grid.
- Board arrows carry sharp parchment eval tags (tobacco SF / denim LC0), upright and legible; hover names the engine.
- ENGINE LINE plate: idle prompt → arrow click → bot-labelled engine board on both sides; flip and deselect behave; header span stays `—`.

- [ ] **Step 5: Update the issue + memory**

```bash
gh issue comment 208 --body "Live-review fixes + two design changes landed: move-chip CSS now ships in main.css (was an unapplied per-partial link); THIS MOVE plate aligned with the boards grid; board arrow labels are sharp parchment eval tags (engine by colour); engine-line board now labels both sides as the bot + search setting (SF bot · depth N / LC0 bot · nodes N), replacing the old engine-lines-header strip. Remaining: Win%/SF-cp/LC0-WDL charts, PGN panel, hero/empty-state."
```

Update the `project_208_analysis_restyle` memory: mark the three live-review issues fixed + the engine-line bot-label change done; note remaining elements = charts / PGN / hero.

---

## Self-review notes

- **Spec coverage:** Item 1 chips→main.css (T1) ✓; Item 2 alignment (T2) ✓; Item 3 arrow tag — eval-only label (T3) + parchment tag/CSS/a11y (T4) ✓; Item 4 bot player labels (T5) + header removal/idle prompt/JS cleanup (T6) ✓; Tailwind rebuild last (T7) ✓; charts/PGN/hero explicitly out of scope ✓.
- **Placeholder scan:** none — every code step shows concrete content. (Line numbers are current-state hints; re-confirm before editing.)
- **Type/name consistency:** `bot_label`, `top_sym`/`top_side`/`bottom_sym`/`bottom_side` defined in the view (T5) and consumed by the same names in the partial (T5). `.engine-lines-idle` created in markup (T6 Step 1), styled (T6 Step 2), toggled in `_clearEngineLineBoard` (show) + `htmx:afterSwap` (hide) (T6 Steps 4-5). `_arrow_label` returns eval-only consistently across T3 (data) and the tag text in T4 (`arrowData.label`). `board-arrow-label-box` / `board-arrow-label-rule--{sf,lc0}` / `board-arrow-label--{sf,lc0}` classes defined in CSS (T4 Step 1) match those set in JS (T4 Step 3). `_UNICODE_MINUS` imported in the test (T3) matches the module constant used by `_arrow_label`.
