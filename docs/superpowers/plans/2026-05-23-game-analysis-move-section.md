# Game Analysis — Move Analysis Section Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the Game Analysis page's "Move Analysis" section into the Du Bois plate language — a full-width `THIS MOVE` chips plate plus two aligned board plates (`POSITION` + `ENGINE LINE`) — *and rebuild the engine-lines continuation explorer scaffold that the #186 rewrite dropped*.

**Architecture:** Mostly template + CSS + vanilla-JS changes on the `issue/208-restyle-game-analysis-page` worktree. Plates reuse the existing `.wc-card` / `.wc-card__head` / `.card-info` classes from `main.css` (built for the SF/LC0 cards). Chip styling stays in the standalone `static/games/moveChips.css` (linked directly, **not** compiled into `tailwind.css`, so no rebuild needed for chip CSS). The engine-lines scaffold is restored inside an `ENGINE LINE` plate using the IDs `engineLines.js` already expects, then its continuation list is converted from an HTML `<table>` to an inline flowing SAN line.

**Tech Stack:** Django templates + HTMX, vanilla JS, hand-written CSS with `:root` design tokens, pytest (Django test client). Tailwind v4 is a committed artifact (`tailwind.css`) compiled from `main.css` under **Node 22**.

**Spec:** `docs/superpowers/specs/2026-05-22-game-analysis-restyle-design.md` → "Move Analysis section — locked design".

**Key reference — the original engine-lines scaffold** (dropped by #186, recovered from `git show 8330a50^:services/app/templates/games/analysis.html`) is reproduced verbatim in Task 6. The JS in `static/games/engineLines.js` still references these IDs: `engine-lines-shell`, `engine-lines-header`, `engine-lines-container`, `engine-lines-loading`, `engine-lines-controls`, `engine-lines-btn-{start,prev,play,next,end}`, `engine-lines-slider`, `engine-lines-ply-label`, `engine-line-san-panel`, `engine-line-tbody`, plus `engine-line-player-spacer` (in `_engine_line_partial.html`).

**Conventions for every task:**
- Work in the worktree: `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+208-restyle-game-analysis`. Verify `git branch --show-current` is `issue/208-restyle-game-analysis-page` before committing.
- Activate the venv from repo root before pytest: `source ../../.venv/bin/activate` (the venv is at the **repo root**, not `services/app`). Run pytest from `services/app`.
- Tests live in `services/app/games/tests/test_*.py` (never `games/tests.py` — it's dead).
- Visual/JS behavior has **no unit-test harness** (no JS runner); verify those by live review per `project_run_app_locally_worktree` (run with `DEBUG=True AUTH_ENABLED=True`).
- Run `bandit -ll <file>` on any edited `.py` before commit (none expected to be risky here).

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `services/app/games/chip_data.py` | Add `source` ("SF"/"LC0") to each chip dict | 1 |
| `services/app/games/views.py` (`chips_partial`) | Pass `ply` + `move_label` to the chips partial | 2 |
| `services/app/templates/games/partials/_move_chips.html` | THIS MOVE plate frame + chips grouped by source with inline prefix | 3 |
| `services/app/static/games/moveChips.css` | Form-2 tile styling (sharp, band top-rule), muted draw chip, prefix label, plate body | 4 |
| `services/app/templates/games/analysis.html` | POSITION plate wrapper; rebuilt ENGINE LINE plate + scaffold; inline continuation container + its CSS | 5,6,7 |
| `services/app/templates/games/_board_partial.html` (`<style>`) | Hex → `:root` token cleanup | 5 |
| `services/app/static/games/engineLines.js` | Inline continuation render; top-bar alignment; hex → token | 7,8 |
| `services/app/templates/games/_engine_line_partial.html` | Token cleanup; top context bar markup | 8 |
| `services/app/games/tests/test_chip_data.py` | `source` field assertions | 1 |
| `services/app/games/tests/test_partial_routes.py` | Chips partial content assertions | 2,3 |
| `services/app/games/tests/test_view_game_analysis_shell.py` | Plate + scaffold presence assertions | 5,6 |

---

## Task 1: Chip data — add `source` field

**Files:**
- Modify: `services/app/games/chip_data.py:31-41` (`_chip`) and `:60-67` (`chips_for_ply` candidates)
- Test: `services/app/games/tests/test_chip_data.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_chip_data.py`:

```python
def test_chips_carry_engine_source():
    """Each chip dict exposes a human engine source: SF for Stockfish, LC0 for Leela."""
    from games.chip_data import _chip
    assert _chip("sf", "Blunder", "t")["source"] == "SF"
    assert _chip("lc0_base", "Mistake", "t")["source"] == "LC0"
    assert _chip("lc0_draw", "Simplification", "t")["source"] == "LC0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_chip_data.py::test_chips_carry_engine_source -v`
Expected: FAIL with `KeyError: 'source'`.

- [ ] **Step 3: Implement the `source` field**

In `services/app/games/chip_data.py`, replace `_chip` with:

```python
def _chip(kind: str, label: str | None, title: str) -> dict | None:
    """Build one chip dict, or None when ``label`` is empty/None.

    ``source`` is the display engine name ("SF" for Stockfish, "LC0" for either
    Leela severity or draw-character), used for the inline prefix label.
    """
    if not label:
        return None
    return {
        "kind": kind,
        "label": label,
        "css_label": _css_label(label),
        "title": title,
        "source": "SF" if kind == "sf" else "LC0",
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && pytest games/tests/test_chip_data.py -v`
Expected: PASS (all chip_data tests green).

- [ ] **Step 5: Commit**

```bash
git add services/app/games/chip_data.py services/app/games/tests/test_chip_data.py
git commit -m "feat(#208): add engine source label to move chips"
```

---

## Task 2: Chips view — pass `ply` and `move_label`

**Files:**
- Modify: `services/app/games/views.py:492-510` (`chips_partial`)
- Test: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_partial_routes.py`:

```python
def test_chips_partial_has_move_label(client, new_schema_game_factory):
    """Chips partial header shows a 'Move N · Side' subject label derived from ply."""
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Move 2" in body      # ply 3 → move (3+1)//2 = 2
    assert "White" in body       # ply 3 is odd → White moved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_partial_routes.py::test_chips_partial_has_move_label -v`
Expected: FAIL (no "Move 2" in body — template not updated yet; this test also depends on Task 3 markup, so it stays red until Task 3).

- [ ] **Step 3: Pass `ply` + `move_label` from the view**

In `services/app/games/views.py`, replace the body of `chips_partial` after `data = _load_or_404(slug)`:

```python
    data = _load_or_404(slug)
    ply = int(request.GET.get("ply", 0) or 0)
    if ply <= 0:
        move_label = "Start position"
    else:
        move_no = (ply + 1) // 2
        side = "White" if ply % 2 else "Black"
        move_label = f"Move {move_no} · {side}"
    return render(request, "games/partials/_move_chips.html", {
        "chips": chips_for_ply(data, ply),
        "ply": ply,
        "move_label": move_label,
    })
```

- [ ] **Step 4: Run bandit on the edited view**

Run: `cd services/app && bandit -ll games/views.py`
Expected: no Medium/High findings.

- [ ] **Step 5: Commit**

```bash
git add services/app/games/views.py services/app/games/tests/test_partial_routes.py
git commit -m "feat(#208): pass move_label + ply to chips partial"
```

(The new test remains red until Task 3 renders `move_label`; that's expected — commit the view change now, the test goes green in Task 3.)

---

## Task 3: THIS MOVE plate + inline source prefixes (template)

**Files:**
- Modify: `services/app/templates/games/partials/_move_chips.html` (full rewrite)
- Test: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_partial_routes.py`:

```python
def test_chips_partial_is_du_bois_plate(client, new_schema_game_factory):
    """Chips partial renders inside a wc-card plate titled 'This Move' with source prefixes."""
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=3")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "wc-card" in body              # Du Bois plate frame
    assert "This Move" in body            # plate title
    assert "move-chip__source" in body    # inline SF/LC0 prefix label class
    assert "border-radius: 999px" not in body  # no rounded pills leaking via inline style
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_partial_routes.py::test_chips_partial_is_du_bois_plate -v`
Expected: FAIL ("wc-card" not in body).

- [ ] **Step 3: Rewrite the chips partial**

Replace the entire contents of `services/app/templates/games/partials/_move_chips.html`:

```django
{% load static %}
<link rel="stylesheet" href="{% static 'games/moveChips.css' %}">
<section class="wc-card move-chips-card" aria-label="Move-quality tags for this move">
  <header class="wc-card__head">
    <h3>This Move</h3>
    <span class="move-chips-card__sub">{{ move_label }}</span>
  </header>
  <div class="move-chips">
  {% regroup chips by source as source_groups %}
  {% for grp in source_groups %}
    <span class="move-chip__source">{{ grp.grouper }}</span>
    {% for c in grp.list %}
      <span class="move-chip move-chip--{{ c.kind }} move-annotation-{{ c.css_label }}"
            title="{{ c.title }}: {{ c.label }}">{% if c.kind == 'lc0_draw' %}~ {% endif %}{{ c.label }}</span>
    {% endfor %}
  {% empty %}
    <span class="move-chips__empty">No engine tags for this move.</span>
  {% endfor %}
  </div>
</section>
```

The `{% if c.kind == 'lc0_draw' %}~ {% endif %}` prefix renders the spec's leading `~`
on draw-character chips for *display only* — `label`/`css_label` stay raw so the
`move-annotation-<band>` class still resolves and existing `test_chip_data` assertions
are untouched.

- [ ] **Step 4: Run both chips partial tests to verify they pass**

Run: `cd services/app && pytest games/tests/test_partial_routes.py::test_chips_partial_is_du_bois_plate games/tests/test_partial_routes.py::test_chips_partial_has_move_label -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/partials/_move_chips.html
git commit -m "feat(#208): wrap move chips in THIS MOVE plate with source prefixes"
```

---

## Task 4: Chip form-2 tile styling (moveChips.css)

**Files:**
- Modify: `services/app/static/games/moveChips.css` (full rewrite of chip rules)

No Tailwind rebuild needed — `moveChips.css` is linked directly, not compiled into `tailwind.css`. Verification is by live review.

- [ ] **Step 1: Rewrite `moveChips.css`**

Replace the entire contents of `services/app/static/games/moveChips.css`:

```css
/*
 * Title: moveChips.css — Move-category chip row styles (Du Bois plate)
 * Description:
 *   Styles for the .move-chips strip inside the THIS MOVE plate. Chips are
 *   sharp "form-2" tiles: parchment background with a band-coloured top rule
 *   (the same idiom as the card stat tiles). The band colour comes from the
 *   shared .move-annotation-* palette, re-mapped here to the chip's top border.
 *   LC0 draw-character chips (.move-chip--lc0_draw) are visually muted so they
 *   stay subordinate to the severity chip.
 *
 * Changelog:
 *   2026-05-21 (#186): Initial (rounded pills).
 *   2026-05-23 (#208): Du Bois restyle — sharp top-rule tiles, source prefix.
 */

/* ── Plate sub-label in the header ─────────────────────────────────────────── */
.move-chips-card__sub {
  font-family: var(--font-mono, 'DM Mono', monospace);
  font-size: 0.6rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-peat, #5C4A2A);
}

/* ── Container ─────────────────────────────────────────────────────────────── */
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

/* ── Inline engine-source prefix (SF / LC0) ────────────────────────────────── */
.move-chip__source {
  font-family: var(--font-mono, 'DM Mono', monospace);
  font-size: 0.55rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-rust, #8B3A2A);
  margin-left: 0.35rem;
}
.move-chip__source:first-child { margin-left: 0; }

/* ── Form-2 tile ───────────────────────────────────────────────────────────── */
.move-chip {
  display: inline-flex;
  align-items: center;
  padding: 0.2rem 0.6rem 0.15rem;
  border-radius: 0;                 /* sharp — no pills */
  font-family: var(--font-mono, 'DM Mono', monospace);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  white-space: nowrap;
  cursor: default;
  color: var(--color-ebony, #1A1410);
  background: var(--color-parchment, #F5F0E8);
  border: 1px solid color-mix(in srgb, var(--color-peat) 25%, transparent);
  border-top: 2.5px solid var(--color-band, #C9B998);  /* band colour set below */
}

/* Band colour → top rule. .move-annotation-* sets `background`; we re-map the
   same tokens to the chip's top border so the tile reads as a stat tile. */
.move-chip.move-annotation-brilliant  { border-top-color: var(--color-teal); }
.move-chip.move-annotation-best       { border-top-color: var(--color-emerald); }
.move-chip.move-annotation-great      { border-top-color: var(--color-leaf); }
.move-chip.move-annotation-excellent  { border-top-color: var(--color-leaf); }
.move-chip.move-annotation-good       { border-top-color: var(--color-leaf); }
.move-chip.move-annotation-inaccuracy { border-top-color: var(--color-saffron); }
.move-chip.move-annotation-mistake    { border-top-color: var(--color-ember); }
.move-chip.move-annotation-blunder    { border-top-color: var(--color-vermilion-bright); }
/* LC0 draw-character bands */
.move-chip.move-annotation-simplification { border-top-color: var(--color-emerald); }
.move-chip.move-annotation-risky          { border-top-color: var(--color-saffron); }
.move-chip.move-annotation-losing_blunder { border-top-color: var(--color-ember); }
.move-chip.move-annotation-missed_win     { border-top-color: var(--color-vermilion-bright); }

/* Re-mapping must override .move-annotation-*'s `background` (which would fill
   the whole chip). Keep the parchment fill. */
.move-chip[class*="move-annotation-"] { background: var(--color-parchment, #F5F0E8); }

/* ── Engine-source variants ───────────────────────────────────────────────── */
.move-chip--sf,
.move-chip--lc0_base { /* primary — full weight, no modifier */ }

.move-chip--lc0_draw {
  /* draw-character chips: muted + subordinate */
  opacity: 0.5;
  font-weight: 600;
  font-size: 0.66rem;
  border-top-width: 1.5px;
}
```

- [ ] **Step 2: Live review**

Per `project_run_app_locally_worktree`, run the app (`DEBUG=True AUTH_ENABLED=True`) and open a game analysis page. Confirm: chips are sharp parchment tiles with a band-coloured top rule, `SF`/`LC0` prefixes precede each engine's chips, the draw chip is muted, and there are no rounded pills.

- [ ] **Step 3: Commit**

```bash
git add services/app/static/games/moveChips.css
git commit -m "style(#208): form-2 sharp move-chip tiles with band top-rule"
```

---

## Task 5: POSITION board plate + token cleanup

**Files:**
- Modify: `services/app/templates/games/analysis.html:42-47` (boards grid — wrap `#board-container`)
- Modify: `services/app/templates/games/_board_partial.html:55-78` (`<style>` block — hex → tokens)
- Test: `services/app/games/tests/test_view_game_analysis_shell.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_view_game_analysis_shell.py`:

```python
def test_position_plate_present(client, new_schema_game_factory):
    """The board lives inside a wc-card POSITION plate."""
    game = new_schema_game_factory()
    resp = client.get(f"/games/{game.slug}/analysis/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "position-plate" in body
    assert ">Position<" in body
```

(If the analysis URL differs, copy the exact `reverse(...)`/path already used by the other tests in this file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py::test_position_plate_present -v`
Expected: FAIL ("position-plate" not in body).

- [ ] **Step 3: Wrap the board in a POSITION plate**

In `services/app/templates/games/analysis.html`, replace the `#boards-container` grid (current lines 42-47) with:

```django
  <div id="boards-container" style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;align-items:start;">
    <section class="wc-card position-plate" aria-label="Game position">
      <header class="wc-card__head">
        <h3>Position</h3>
        <span class="card-info" tabindex="0" aria-label="Analysis run info">ⓘ
          <div class="card-pop card-info-pop"><h4>Run info</h4><p>Engine arrows and move tags reflect the stored analysis for this game.</p></div>
        </span>
      </header>
      <div id="board-container"
           hx-get="/_partials/games/{{ game.slug }}/board/?orientation={{ initial_perspective }}"
           hx-trigger="load" hx-swap="innerHTML">Loading board…</div>
    </section>
    <section class="wc-card engine-line-plate" aria-label="Engine line explorer">
      {# ENGINE LINE plate header + scaffold added in Task 6 #}
      <div id="engine-lines-shell">{# rebuilt in Task 6 #}</div>
    </section>
  </div>
```

- [ ] **Step 4: Token cleanup in the board partial `<style>`**

In `services/app/templates/games/_board_partial.html`, within the `<style>` block (lines ~55-78), replace hardcoded hex with tokens (visual idiom unchanged):

- `#1A1A1A` → `var(--color-ebony)`
- `#8B3A2A` → `var(--color-rust)`
- `#D4C4A0` → `var(--color-card-border-soft)`
- `#D4A843` (slider `accent-color`, in the markup `<input>` at line ~43) → `var(--color-gold)`
- arrow label `#A8781B` → `var(--color-tobacco)`; `#35586F` → `var(--color-denim)`
- player-name `Georgia,serif` → `var(--font-serif)`; mono → `var(--font-mono)`

Leave geometry (px, borders) as-is.

- [ ] **Step 5: Run test to verify it passes + live review**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py::test_position_plate_present -v`
Expected: PASS.
Live review: the board sits inside a POSITION plate matching the SF/LC0 cards; the right plate is an empty `ENGINE LINE` shell for now.

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/templates/games/_board_partial.html services/app/games/tests/test_view_game_analysis_shell.py
git commit -m "feat(#208): wrap board in POSITION plate; tokenize board styles"
```

---

## Task 6: Rebuild the engine-lines scaffold inside the ENGINE LINE plate

**Files:**
- Modify: `services/app/templates/games/analysis.html` (`engine-lines-shell` inside the `engine-line-plate` section from Task 5)
- Test: `services/app/games/tests/test_view_game_analysis_shell.py`

This restores the scaffold the #186 rewrite dropped, using token-based styling. After this task the explorer works again (arrow click → board + continuation table); Task 7 swaps the table for an inline line.

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_view_game_analysis_shell.py`:

```python
def test_engine_line_scaffold_present(client, new_schema_game_factory):
    """The engine-lines scaffold IDs that engineLines.js needs are present again."""
    game = new_schema_game_factory()
    resp = client.get(f"/games/{game.slug}/analysis/")
    body = resp.content.decode()
    assert resp.status_code == 200
    for el_id in ['id="engine-lines-container"', 'id="engine-lines-controls"',
                  'id="engine-line-san-panel"', 'id="engine-line-tbody"',
                  ">Engine Line<"]:
        assert el_id in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py::test_engine_line_scaffold_present -v`
Expected: FAIL (IDs absent).

- [ ] **Step 3: Rebuild the scaffold**

In `services/app/templates/games/analysis.html`, replace the `engine-line-plate` section's body (the placeholder from Task 5) with the header + recovered scaffold, tokenized:

```django
    <section class="wc-card engine-line-plate" aria-label="Engine line explorer">
      <header class="wc-card__head">
        <h3>Engine Line</h3>
        <span id="engine-lines-context" class="engine-line-plate__ctx">—</span>
      </header>
      <div id="engine-lines-shell" style="position:relative;">
        <div id="engine-lines-header"
             style="font-family:var(--font-mono);font-size:.7rem;letter-spacing:.08em;text-transform:uppercase;color:var(--color-rust);padding:5px 8px;border-top:2.5px solid var(--color-ebony);border-bottom:1px solid var(--color-ebony);min-height:31px;box-sizing:border-box;display:flex;align-items:center;font-weight:700;">
          Click an engine arrow on the board to explore the continuation.
        </div>
        <div id="engine-lines-container" style="position:relative;color:var(--color-rust);font-family:var(--font-mono);font-size:.72rem;">
          {# Engine-line board is loaded here via HTMX on arrow click #}
          <div id="engine-lines-loading" style="display:none;">Loading…</div>
        </div>
        <div id="engine-lines-controls" style="display:none;align-items:center;gap:5px;padding:8px 0 6px;justify-content:center;flex-wrap:wrap;border-top:1px solid var(--color-card-border-soft);">
          <button class="board-btn" id="engine-lines-btn-start" title="Start" disabled>&#x23EE;</button>
          <button class="board-btn" id="engine-lines-btn-prev" title="Previous" disabled>&#x25C0;</button>
          <button class="board-btn" id="engine-lines-btn-play" title="Play/Pause" disabled>&#x25B6;</button>
          <button class="board-btn" id="engine-lines-btn-next" title="Next" disabled>&#x25B6;&#xFE0E;</button>
          <button class="board-btn" id="engine-lines-btn-end" title="End" disabled>&#x23ED;</button>
          <input type="range" id="engine-lines-slider" min="0" max="0" value="0" style="flex:1;max-width:220px;accent-color:var(--color-gold);" disabled>
          <span id="engine-lines-ply-label" style="font-family:var(--font-mono);font-size:.68rem;color:var(--color-rust);min-width:72px;text-align:center;letter-spacing:.04em;">—</span>
        </div>
      </div>
      <details id="engine-line-san-panel" class="move-list-panel" style="display:none;">
        <summary class="move-list-summary">Continuation</summary>
        <div class="move-list-body">
          <div id="engine-line-table-wrap" class="move-list-wrap">
            <table id="engine-line-table" class="move-list-table">
              <thead><tr><th class="move-list-number-header"></th><th>White</th><th>Black</th></tr></thead>
              <tbody id="engine-line-tbody"></tbody>
            </table>
          </div>
        </div>
      </details>
    </section>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py -v`
Expected: PASS (all shell tests).

- [ ] **Step 5: Live review — explorer works again**

Run the app, open a game with engine arrows, click an arrow: the engine-line board mounts in the right plate, the controls enable, and the Continuation table populates (still a table — converted next task). Boards may not yet line up perfectly (Task 8).

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/games/tests/test_view_game_analysis_shell.py
git commit -m "feat(#208): rebuild engine-lines scaffold inside ENGINE LINE plate"
```

---

## Task 7: Inline flowing continuation line (replace the table)

**Files:**
- Modify: `services/app/templates/games/analysis.html` (`engine-line-san-panel` body — replace table with inline container + add CSS)
- Modify: `services/app/static/games/engineLines.js:486-583` (`renderContinuationTable`, `renderContinuationSelection`)

No unit-test harness for this JS — verify by live review.

- [ ] **Step 1: Swap the table markup for an inline container**

In `services/app/templates/games/analysis.html`, replace the `engine-line-san-panel` `<details>` body (the `move-list-body` div) with:

```django
      <details id="engine-line-san-panel" class="move-list-panel" style="display:none;">
        <summary class="move-list-summary">Continuation</summary>
        <div class="move-list-body">
          <div id="engine-line-moves" class="engine-line-inline"></div>
        </div>
      </details>
```

- [ ] **Step 2: Add the inline-line CSS**

Add to the existing `<style>` block in `analysis.html` (or create one in the `{% block content %}`):

```css
.engine-line-inline {
  font-family: var(--font-serif);
  font-size: 0.95rem;
  line-height: 1.8;
  color: var(--color-ebony);
  padding: 6px 10px 10px;
}
.engine-line-inline .eln-num {
  font-family: var(--font-mono);
  font-size: 0.62rem;
  color: var(--color-peat);
  margin: 0 2px 0 6px;
}
.engine-line-inline .eln-mv { padding: 0 3px; cursor: pointer; }
.engine-line-inline .eln-mv:hover { background: color-mix(in srgb, var(--color-gold) 18%, transparent); }
.engine-line-inline .eln-mv.is-active {
  background: color-mix(in srgb, var(--color-gold) 35%, transparent);
  box-shadow: inset 0 -2px 0 var(--color-forest);
}
.engine-line-inline .eln-empty { font-family: var(--font-mono); font-size: 0.72rem; color: var(--color-peat); opacity: 0.7; }
```

- [ ] **Step 3: Rewrite the continuation renderer in `engineLines.js`**

Replace `renderContinuationTable` (lines ~486-564). First update the element lookup `_getEngineLineContinuationElements` (lines ~107-112) to also return the inline container:

```javascript
  function _getEngineLineContinuationElements() {
    return {
      panel: document.getElementById('engine-line-san-panel'),
      moves: document.getElementById('engine-line-moves'),
    };
  }
```

Update the two call sites that reference `.tbody` (in `_clearEngineLineBoard` line ~231 and wherever `continuationTbody` is read) to use `.moves`, and replace the module-level `var continuationPanel = ...; var continuationTbody = ...;` (line ~454) with:

```javascript
  var continuationPanel = document.getElementById('engine-line-san-panel');
  var continuationMoves = document.getElementById('engine-line-moves');
```

Then replace `renderContinuationTable` with an inline builder:

```javascript
  /**
   * Render the continuation as an inline flowing SAN line below the board.
   * Each move is a clickable <span class="eln-mv"> carrying its engine-line ply.
   */
  function renderContinuationTable() {
    var firstAbsolutePly = firstContinuationAbsolutePly();
    if (!continuationPanel || !continuationMoves) {
      return;
    }
    continuationMoves.innerHTML = '';
    continuationPanel.style.display = '';
    if (window.WoodLeagueMovePanels && typeof window.WoodLeagueMovePanels.sync === 'function') {
      window.WoodLeagueMovePanels.sync();
    }

    if (!sanList.length || firstAbsolutePly === null) {
      var empty = document.createElement('span');
      empty.className = 'eln-empty';
      empty.textContent = 'No continuation moves stored.';
      continuationMoves.appendChild(empty);
      return;
    }

    sanList.forEach(function (san, index) {
      var absolutePly = firstAbsolutePly + index;
      var moveNumber = Math.ceil(absolutePly / 2);
      var isWhite = absolutePly % 2 === 1;
      if (isWhite) {
        var num = document.createElement('span');
        num.className = 'eln-num';
        num.textContent = moveNumber + '.';
        continuationMoves.appendChild(num);
      } else if (index === 0) {
        // line starts on a Black move — show "N..."
        var bnum = document.createElement('span');
        bnum.className = 'eln-num';
        bnum.textContent = moveNumber + '…';
        continuationMoves.appendChild(bnum);
      }
      var mv = document.createElement('span');
      mv.className = 'eln-mv';
      mv.textContent = san;
      mv.dataset.engineLinePly = String(index + 1);
      mv.onclick = function () { window.WoodLeagueEngineLines.setPly(index + 1); };
      continuationMoves.appendChild(mv);
      continuationMoves.appendChild(document.createTextNode(' '));
    });
  }
```

Replace `renderContinuationSelection` (lines ~571-583):

```javascript
  function renderContinuationSelection(ply) {
    if (!continuationMoves) {
      return;
    }
    continuationMoves.querySelectorAll('.eln-mv[data-engine-line-ply]').forEach(function (mv) {
      var isActive = (parseInt(mv.dataset.engineLinePly, 10) || 0) === ply;
      mv.classList.toggle('is-active', isActive);
      if (isActive) {
        mv.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    });
  }
```

- [ ] **Step 4: Grep for stale references**

Run: `cd services/app && grep -n "continuationTbody\|engine-line-tbody\|engine-line-table\|move-list-cell" static/games/engineLines.js`
Expected: no remaining `continuationTbody` / `engine-line-tbody` references in `engineLines.js`. (The old table IDs in `analysis.html` were removed in Step 1.)

- [ ] **Step 5: Live review**

Run the app, click an engine arrow: the Continuation shows an inline flowing serif line (`24.♘f5 ♝xf5 25.…`); clicking a move jumps the engine-line board and the active move is boxed (gold wash + forest underline); stepping with the controls moves the highlight.

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/static/games/engineLines.js
git commit -m "feat(#208): inline flowing engine-line continuation (replaces table)"
```

---

## Task 8: Align the two boards + token cleanup in engine-line partial/JS

**Files:**
- Modify: `services/app/static/games/engineLines.js:119-135` (`_applyEngineLineBorderStyles`) + any remaining hex
- Modify: `services/app/templates/games/_engine_line_partial.html` (top context bar markup + token cleanup)

Goal: the engine-line board sits at the same vertical position as the game board — the engine plate gets a top context bar (height-matched to the game board's top player-label) and the existing bottom spacer, both tokenized.

- [ ] **Step 1: Add a top context bar to the engine-line partial**

In `services/app/templates/games/_engine_line_partial.html`, add a context bar above the board SVG wrap (inside `#engine-line-board-inner`, before `.board-wrap`), matching the player-label geometry:

```django
  <div class="engine-line-context-bar" id="engine-line-context-bar" aria-hidden="true"></div>
  <div class="board-wrap" id="engine-line-board-svg-wrap"></div>
  <div class="engine-line-player-spacer" id="engine-line-player-spacer" aria-hidden="true"></div>
```

- [ ] **Step 2: Tokenize + extend `_applyEngineLineBorderStyles`**

In `services/app/static/games/engineLines.js`, replace `_applyEngineLineBorderStyles` (lines ~119-135) to style both the new top context bar and the bottom spacer with the same side-based ebony rules the main board uses (tokens via CSS custom properties read from the document root are not available in inline JS, so use the literal token values' CSS variable through `style.borderTop = '... var(--color-ebony)'`):

```javascript
  function _applyEngineLineBorderStyles() {
    var perspective = (window.WoodLeagueAnalysis && window.WoodLeagueAnalysis.getState().perspective) || 'white';
    var topSide = perspective === 'white' ? 'Black' : 'White';
    var bottomSide = perspective === 'white' ? 'White' : 'Black';
    var topBar = document.getElementById('engine-line-context-bar');
    var spacer = document.getElementById('engine-line-player-spacer');

    if (topBar) {
      topBar.style.minHeight = '31px';
      topBar.style.boxSizing = 'border-box';
      topBar.style.borderTop = topSide === 'White' ? '0' : '2.5px solid var(--color-ebony)';
      topBar.style.borderBottom = topSide === 'Black' ? '0' : '1px solid var(--color-ebony)';
    }
    if (spacer) {
      spacer.style.minHeight = '31px';
      spacer.style.boxSizing = 'border-box';
      spacer.style.borderTop = bottomSide === 'White' ? '0' : '1px solid var(--color-ebony)';
      spacer.style.borderBottom = bottomSide === 'Black' ? '0' : '2.5px solid var(--color-ebony)';
    }
  }
```

Also update the old `engine-lines-header` border styling block if it still sets `#1A1A1A` (lines ~123-129) — point it at the new `engine-line-context-bar` or remove if superseded.

- [ ] **Step 3: Remaining hex → token sweep in engineLines.js**

Run: `cd services/app && grep -n "#1A1A1A\|#8B3A2A\|#D4A843\|#B53541\|#F2E6D0" static/games/engineLines.js`
For each hit, replace with the matching token: `#1A1A1A`→`var(--color-ebony)`, `#8B3A2A`→`var(--color-rust)`, `#D4A843`→`var(--color-gold)`, `#B53541`→`var(--color-crimson)`, `#F2E6D0`→`var(--color-parchment)`. (These appear in inline `style.*` assignments and error-div colors, e.g. line ~156.)

- [ ] **Step 4: Live review — alignment**

Run the app, click an arrow: the engine-line board's top and bottom edges line up with the game board's top/bottom player-label rules, in both orientations (flip the board to confirm the side-based rules swap correctly).

- [ ] **Step 5: Commit**

```bash
git add services/app/static/games/engineLines.js services/app/templates/games/_engine_line_partial.html
git commit -m "feat(#208): align engine-line board with game board; tokenize engine-line styles"
```

---

## Task 9: Tailwind rebuild check + full verification

**Files:**
- Possibly: `services/app/static/css/tailwind.css` (only if regenerated)

- [ ] **Step 1: Rebuild Tailwind under Node 22**

The plates reuse existing `.wc-card` utilities and template changes use custom classes + inline styles, so `tailwind.css` likely does not change — but the css-staleness CI gate requires the committed artifact to match. Rebuild and diff:

```bash
cd services/app
PATH="$(npx node@22 -e 'process.stdout.write(require("path").dirname(process.execPath))'):$PATH" bin/build_tailwind.sh
git diff --stat static/css/tailwind.css
```

(See `project_tailwind_node22` / `project_tailwind_build`: must build under Node 22 or the byte output differs and CI fails.)

- [ ] **Step 2: Commit the artifact only if it changed**

If `git diff --stat` shows a change:

```bash
git add services/app/static/css/tailwind.css
git commit -m "build(#208): rebuild tailwind.css for move-analysis restyle"
```

If no change, skip — nothing to commit.

- [ ] **Step 3: Run the full relevant test suite**

```bash
cd services/app && pytest games/tests/test_chip_data.py games/tests/test_partial_routes.py games/tests/test_view_game_analysis_shell.py -v
```

Expected: all PASS.

- [ ] **Step 4: Final live review of the whole section**

Open a game analysis page and confirm against the spec: full-width `THIS MOVE` plate with sharp source-prefixed chips; `POSITION` and `ENGINE LINE` plates side by side; empty state prompt; arrow click → mounted engine board + inline flowing continuation with boxed active move; boards aligned; flip works.

- [ ] **Step 5: Update the issue + memory**

```bash
gh issue comment 208 --body "Move Analysis section restyled + engine-lines explorer rebuilt (was dropped by the #186 rewrite). Full-width THIS MOVE chips plate, POSITION/ENGINE LINE board plates, inline flowing continuation. Next: charts, PGN panel, hero/empty-state."
```

Update `project_208_analysis_restyle` memory: mark Move Analysis section done; note the engine-lines scaffold was rebuilt; next elements = charts / PGN / hero.

---

## Self-review notes

- **Spec coverage:** full-width THIS MOVE plate (T3/T4) ✓; form-2 tiles + inline SF/LC0 prefixes (T3/T4) ✓; muted draw chip with leading `~` display prefix (T3 template + T4 `.move-chip--lc0_draw`) ✓; POSITION plate + token cleanup (T5) ✓; ENGINE LINE plate + empty state + scaffold rebuild (T6) ✓; inline continuation (T7) ✓; board alignment (T8) ✓; Tailwind rebuild last (T9) ✓; PGN deferred ✓.
- **Placeholder scan:** none — all code blocks are concrete. (Line numbers are current-state hints; re-confirm before editing.)
- **Type/name consistency:** `engine-line-moves` container + `.eln-mv[data-engine-line-ply]` used consistently across T7 builder and selection; `source` field used in T1 (data), T3 (regroup), T4 (no dependency). `_getEngineLineContinuationElements` returns `{panel, moves}` consistently.

---

## Live-review findings — 2026-05-23 (FIX NEXT SESSION)

All 9 tasks implemented, reviewed, committed (`ef99698`…`a345885`); 27 tests pass. Live review in the running app surfaced three issues to pick up next session. None are merged.

1. **Chips render unstyled.** The form-2 tile CSS is not applying in the browser.
   - **Root cause (likely):** chip styles live in the standalone `services/app/static/games/moveChips.css`, linked ONLY via a `<link>` inside `_move_chips.html` that is injected through HTMX's `innerHTML` swap into `#move-chips`. `base.html` loads only `tailwind.css`. The injected stylesheet is not being applied to the chips.
   - **Fix:** move the chip rules from `moveChips.css` into `main.css` (`@layer components`, alongside `.wc-card`/`.card-*`) so they ship in the globally-loaded `tailwind.css` — this is what the spec originally intended ("shared chip/plate styling moves into main.css"). Drop the `<link>` (and likely the `moveChips.css` file) from `_move_chips.html`. Rebuild `tailwind.css` under Node 22 afterward. Re-verify the band top-rule colours map for every `move-annotation-*` value (incl. the LC0 draw bands) and that the muted `--lc0_draw` variant reads correctly.
   - Also double-check chips actually have data at the reviewed ply (ply 0 = start shows the empty state "No engine tags for this move." — not a styling bug).

2. **"THIS MOVE" bar not in sync with the boards.** The full-width chips plate's left/right edges don't line up with the `1fr 1fr` boards grid (`#boards-container`) below it.
   - **Fix:** make the THIS MOVE plate share the boards-container's box — same width, horizontal padding/margins, and (if any) container insets — so its edges align with the POSITION plate's left edge and the ENGINE LINE plate's right edge. Check whether `.wc-card` adds margins that break the alignment, and whether the `pg-section` wraps both at the same width.

3. **Board arrow labels need design work.** The SF/LC0 eval labels drawn on the board arrows (`.board-arrow-label` / `--sf` / `--lc0` in `_board_partial.html`, set in JS at `_board_partial.html:362`) look unrefined.
   - **Note:** this was NOT in the Move-Analysis spec — it's a new element. Treat as its own incremental element: brainstorm/mockup the label treatment (legibility on the board, the `cp`/eval text, SF vs LC0 distinction, the white stroke halo) before implementing, like the other elements.

**Suggested order next session:** (1) chips styling (most broken), (2) THIS MOVE alignment, (3) arrow-label design pass (brainstorm first). The remaining spec elements after that: Win%/SF-cp/LC0-WDL charts, PGN panel, page hero + empty state.
