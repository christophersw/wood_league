# Move Analysis — THIS MOVE Card, Arrow Controls & Delta Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the arrow-selection toggle controls, promote THIS MOVE to a first-class HTMX card (synced to the live ply, with identity + quality chips + SF/LC0 score-Δ chips rendered as form-2 tiles), and make every engine arrow label a signed delta-vs-played (SF pawns, LC0 win%).

**Architecture:** Django templates + HTMX + vanilla JS + a little view/data Python, on the `issue/208-restyle-game-analysis-page` worktree. Frame-sensitive deltas (SF cp swing, LC0 μ delta) are locked with **characterization tests first**, then implemented. LC0 per-candidate WDL is plumbed from the model onto the `Lc0MoveRow` dataclass. Tailwind v4 (`tailwind.css`) is a committed artifact rebuilt under **Node 22** at the end.

**Tech Stack:** Django + HTMX, vanilla JS, hand-written CSS with `:root` tokens, pytest (Django test client), Node 22 for Tailwind.

**Spec:** `docs/superpowers/specs/2026-05-25-this-move-card-and-arrow-controls-design.md`.

**Conventions for every task:**
- Work in the worktree: `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+208-restyle-game-analysis`. Verify `git branch --show-current` is `issue/208-restyle-game-analysis-page` before committing.
- Activate venv (absolute path): `source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate`. Run pytest from `services/app`.
- Tests live in `services/app/games/tests/test_*.py` (never `games/tests.py` — dead/shadowed).
- Run `bandit -ll <file>` on any edited `.py`; keep touched functions at radon grade B (`radon cc <file> -s`) — the quality gate hard-fails grade C. Halstead WARN is non-blocking.
- Use plain `Bash`/`grep`/`Read` (vexp does not cover this worktree branch). Do NOT use vexp.
- **Do not rebuild `tailwind.css` until the final task** (rebuild-last). Toggle chips + any new `main.css` look unstyled in a live review until then — expected.

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `services/app/templates/games/analysis.html` | Toggle controls in POSITION header; `#move-chips` ply-sync via `hx-vals` | 1, 3 |
| `services/app/static/css/main.css` | `.arrow-tg*` toggle-chip CSS; (chips CSS already present) | 1 |
| `services/app/games/views.py` (`chips_partial`) | Supply identity + SF/LC0 score-Δ to the card; extract a helper | 2 |
| `services/app/templates/games/partials/_move_chips.html` | Rebuild into the two-column THIS MOVE card (layout B) | 3 |
| `services/app/games/services_v2.py` (`Lc0MoveRow` + loader) | Carry raw played + per-candidate WDL triples | 4 |
| `services/app/games/board_builder.py` (`_arrow_entries_from_row`, `_arrow_label`) | Per-candidate delta-vs-played for both engines | 5 |
| `services/app/games/tests/conftest.py` (`_make_lc0_move_row`) | Populate per-candidate WDL in the LC0 fixture | 4 |
| `services/app/games/tests/test_partial_routes.py` | Card identity + score-Δ + ply assertions | 2, 3 |
| `services/app/games/tests/test_arrow_labels.py` | SF/LC0 arrow delta-vs-played assertions | 5 |
| `services/app/games/tests/test_view_game_analysis_shell.py` | Toggle controls present + defaults | 1 |
| `services/app/games/tests/test_services_v2.py` | `Lc0MoveRow` carries per-candidate WDL | 4 |
| `services/app/static/css/tailwind.css` | Rebuilt under Node 22 | 6 |

---

## Task 1: Arrow-selection toggle controls (F1)

**Files:**
- Modify: `services/app/templates/games/analysis.html` (POSITION plate header)
- Modify: `services/app/static/css/main.css` (add `.arrow-tg*` before the `@layer components` closing `}`, currently the last line of the file)
- Test: `services/app/games/tests/test_view_game_analysis_shell.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_view_game_analysis_shell.py`:

```python
def test_arrow_toggle_controls_present(client, new_schema_game_factory):
    """The POSITION plate header renders the three engine-arrow toggles with defaults.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/games/{game.slug}/analysis/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert 'id="board-sf-toggle"' in body
    assert 'id="board-lc0-toggle"' in body
    assert 'id="board-best-line-toggle"' in body
    # SF + LC0 default on, best-line default off
    assert body.count("checked") >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py::test_arrow_toggle_controls_present -v`
Expected: FAIL (toggle IDs absent).

- [ ] **Step 3: Add the toggle bar to the POSITION plate header**

In `services/app/templates/games/analysis.html`, replace the POSITION plate `<header>` block:

```django
      <header class="wc-card__head">
        <h3>Position</h3>
        <span class="card-info" tabindex="0" aria-label="Analysis run info">ⓘ
          <div class="card-pop card-info-pop"><h4>Run info</h4><p>Engine arrows and move tags reflect the stored analysis for this game.</p></div>
        </span>
      </header>
```

with (toggle group added after the ⓘ):

```django
      <header class="wc-card__head">
        <h3>Position</h3>
        <div class="arrow-toggles" role="group" aria-label="Engine arrow filters">
          <label class="arrow-tg arrow-tg--sf"><input type="checkbox" id="board-sf-toggle" checked onchange="window.boardApplyArrowVisibility && window.boardApplyArrowVisibility()"><span class="arrow-tg__dot"></span>SF</label>
          <label class="arrow-tg arrow-tg--lc0"><input type="checkbox" id="board-lc0-toggle" checked onchange="window.boardApplyArrowVisibility && window.boardApplyArrowVisibility()"><span class="arrow-tg__dot"></span>LC0</label>
          <label class="arrow-tg arrow-tg--best"><input type="checkbox" id="board-best-line-toggle" onchange="window.boardApplyArrowVisibility && window.boardApplyArrowVisibility()"><span class="arrow-tg__box"></span>Best only</label>
        </div>
        <span class="card-info" tabindex="0" aria-label="Analysis run info">ⓘ
          <div class="card-pop card-info-pop"><h4>Run info</h4><p>Engine arrows and move tags reflect the stored analysis for this game.</p></div>
        </span>
      </header>
```

- [ ] **Step 4: Add the toggle-chip CSS**

In `services/app/static/css/main.css`, insert before the final `}` that closes `@layer components` (the last line of the file):

```css

  /* ── Engine-arrow toggle chips (#208) ──────────────────────────────────────
     Sharp Du Bois toggles in the POSITION header. ON via :has(input:checked):
     engine-colour top-rule + dot; OFF: muted + dashed. Best-only is a filter. */
  .arrow-toggles { display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap; }
  .arrow-tg {
    display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.18rem 0.5rem;
    cursor: pointer; font-family: var(--font-mono); font-size: 0.58rem; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase; border-radius: 0;
    color: var(--color-ebony); background: var(--color-parchment);
    border: 1px dashed color-mix(in srgb, var(--color-peat) 28%, transparent); opacity: 0.45;
  }
  .arrow-tg input { position: absolute; opacity: 0; width: 0; height: 0; }
  .arrow-tg__dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: var(--color-peat); }
  .arrow-tg__box { width: 0.66rem; height: 0.66rem; border: 1.5px solid var(--color-ebony);
    display: inline-flex; align-items: center; justify-content: center; font-size: 0.5rem; line-height: 1; }
  .arrow-tg--sf:has(input:checked) { opacity: 1; border-style: solid; border-top: 2.5px solid var(--color-tobacco); }
  .arrow-tg--sf:has(input:checked) .arrow-tg__dot { background: var(--color-tobacco); }
  .arrow-tg--lc0:has(input:checked) { opacity: 1; border-style: solid; border-top: 2.5px solid var(--color-denim); }
  .arrow-tg--lc0:has(input:checked) .arrow-tg__dot { background: var(--color-denim); }
  .arrow-tg--best:has(input:checked) { opacity: 1; border-style: solid; border-top: 2.5px solid var(--color-gold); }
  .arrow-tg--best:has(input:checked) .arrow-tg__box::after { content: "✓"; }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/app && pytest games/tests/test_view_game_analysis_shell.py::test_arrow_toggle_controls_present -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/app/templates/games/analysis.html services/app/static/css/main.css services/app/games/tests/test_view_game_analysis_shell.py
git commit -m "feat(#208): arrow-selection toggle controls in POSITION header"
```

(Visibility behaviour + the chip look are live-reviewed after the Task 6 Tailwind rebuild.)

---

## Task 2: THIS MOVE view — supply identity + score-Δ (F3 data)

**Files:**
- Modify: `services/app/games/views.py` (`chips_partial` + new helper `_this_move_context`)
- Test: `services/app/games/tests/test_partial_routes.py`

The card needs, per ply: `move_no`, `side`, `king_sym`, the move's `chips` + `move_label` (existing), and two score deltas — `sf_delta_pawns` (signed pawns swing of the played move) and `lc0_delta_pct` (signed win-% change). Player name is added in Task 3's template from existing context (`data.white_label`/`black_label`); this task supplies the numeric/identity pieces.

**Delta definitions (mover-relative, signed; negative = worse for the side that moved):**
- `sf_delta_pawns` = `_mover_relative_score(cp_eval[ply] − cp_eval[ply-1], ply is odd) / 100`, where `cp_eval[ply]` is the SF row's `cp_eval` for that ply and `cp_eval[ply-1]` is the previous SF row's `cp_eval` (baseline `0.0` at ply 1). `None` when the SF row is missing.
- `lc0_delta_pct` = `round(lc0_row.delta_mu * 100)` for that ply (matches how `delta_mu` is used for the LC0 arrow label). `None` when missing.

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_partial_routes.py` (the `new_schema_game_factory` seeds SF `cp_eval` 30/−25/40/−35 and LC0 `delta_mu` −0.031/0.044/−0.058/0.065 over plies 1–4):

```python
def test_this_move_partial_has_identity_and_score_deltas(client, new_schema_game_factory):
    """The THIS MOVE partial renders move identity and SF/LC0 score-delta chips.

    Parameters:
        client: Django test client fixture.
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    game = new_schema_game_factory()
    resp = client.get(f"/_partials/games/{game.slug}/chips/?ply=2")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert "Move 1" in body          # ply 2 → move (2+1)//2 = 1
    assert "Black" in body           # ply 2 is even → Black moved
    # SF delta ply2 = cp_eval[2] - cp_eval[1] = -25 - 30 = -55 (White frame),
    # Black moved → mover-relative +55cp → +0.55 pawns
    assert "+0.55" in body
    # LC0 delta ply2 = delta_mu 0.044 * 100 = +4%
    assert "+4%" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_partial_routes.py::test_this_move_partial_has_identity_and_score_deltas -v`
Expected: FAIL (template not updated until Task 3 — and the context keys don't exist yet). This test goes green at the end of Task 3; commit the view change now.

- [ ] **Step 3: Add the `_this_move_context` helper + use it in `chips_partial`**

In `services/app/games/views.py`, add a module-level helper above `chips_partial`:

```python
def _sf_cp_eval_at(data, ply: int) -> float | None:
    """Return the SF row's cp_eval (White-frame) for a ply, or None if absent."""
    row = next((m for m in data.sf_moves if m.ply == ply), None)
    return None if row is None else row.cp_eval


def _this_move_context(data, ply: int) -> dict:
    """Build the THIS MOVE card context for a ply: identity + signed score deltas.

    sf_delta_pawns is the played move's mover-relative eval swing in pawns
    (cp_eval[ply] - cp_eval[ply-1], baseline 0.0 at ply 1). lc0_delta_pct is the
    played move's delta_mu as whole win-% points. Both None when the engine row
    is missing.

    Parameters:
        data: GameAnalysisDataV2 for the game.
        ply (int): 1-indexed half-move ply (0 = start position).

    Returns:
        dict with move_no, side, king_sym, move_label, sf_delta_pawns, lc0_delta_pct.
    """
    if ply <= 0:
        return {
            "move_no": None, "side": None, "king_sym": None,
            "move_label": "Start position",
            "sf_delta_pawns": None, "lc0_delta_pct": None,
        }
    is_white = ply % 2 == 1
    move_no = (ply + 1) // 2
    side = "White" if is_white else "Black"

    cur = _sf_cp_eval_at(data, ply)
    prev = 0.0 if ply == 1 else _sf_cp_eval_at(data, ply - 1)
    sf_delta_pawns = None
    if cur is not None and prev is not None:
        mover_swing = (cur - prev) if is_white else -(cur - prev)
        sf_delta_pawns = round(mover_swing / 100.0, 2)

    lc0_row = next((m for m in data.lc0_moves if m.ply == ply), None)
    lc0_delta_pct = None
    if lc0_row is not None and lc0_row.delta_mu is not None:
        lc0_delta_pct = round(lc0_row.delta_mu * 100)

    return {
        "move_no": move_no, "side": side,
        "king_sym": "♔" if is_white else "♚",
        "move_label": f"Move {move_no} · {side}",
        "sf_delta_pawns": sf_delta_pawns, "lc0_delta_pct": lc0_delta_pct,
    }
```

Then replace the body of `chips_partial` after `data = _load_or_404(slug)`:

```python
    data = _load_or_404(slug)
    ply = int(request.GET.get("ply", 0) or 0)
    context = _this_move_context(data, ply)
    context["chips"] = chips_for_ply(data, ply)
    context["ply"] = ply
    context["white_label"] = data.white_label
    context["black_label"] = data.black_label
    return render(request, "games/partials/_move_chips.html", context)
```

(`data.white_label`/`black_label` are the display names on `GameAnalysisDataV2`; if the attribute differs, use the one the SF/LC0 cards already render — grep `white_label` in `games/cards.py` to confirm.)

- [ ] **Step 4: Verify grade + bandit**

Run: `cd services/app && radon cc games/views.py -s | grep -E "chips_partial|_this_move_context"` → both grade A/B.
Run: `cd services/app && bandit -ll games/views.py` → no Medium/High.

- [ ] **Step 5: Commit**

```bash
git add services/app/games/views.py services/app/games/tests/test_partial_routes.py
git commit -m "feat(#208): THIS MOVE view supplies identity + SF/LC0 score deltas"
```

(The new test stays red until Task 3 renders these — expected.)

---

## Task 3: THIS MOVE card template (layout B) + ply-sync (F3/F4)

**Files:**
- Modify: `services/app/templates/games/partials/_move_chips.html` (full rebuild)
- Modify: `services/app/templates/games/analysis.html` (`#move-chips` ply-sync)
- Modify: `services/app/static/css/main.css` (score-Δ chip CSS, in `@layer components`)
- Test: `services/app/games/tests/test_partial_routes.py`

- [ ] **Step 1: Rebuild the partial into the two-column card**

Replace the entire contents of `services/app/templates/games/partials/_move_chips.html`:

```django
<section class="wc-card move-chips-card" aria-label="This move">
  <header class="wc-card__head"><h3>This Move</h3></header>
  {% if not move_no %}
  <div class="this-move__empty">Start position — no move yet.</div>
  {% else %}
  <div class="this-move">
    <div class="this-move__main">
      <p class="this-move__ident">Move {{ move_no }}
        <span class="this-move__side">{{ king_sym }} {{ side }}{% if side == 'White' %} · {{ white_label }}{% else %} · {{ black_label }}{% endif %}</span>
      </p>
      <p class="this-move__lbl">Move quality</p>
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
    </div>
    <div class="this-move__scores">
      <p class="this-move__lbl this-move__lbl--c">Score Δ</p>
      <div class="scorechips">
        <div class="scorechip scorechip--sf">
          <span class="scorechip__k">SF</span>
          <span class="scorechip__v{% if sf_delta_pawns < 0 %} bad{% endif %}">{% if sf_delta_pawns != None %}{{ sf_delta_pawns|stringformat:"+.2f" }}{% else %}—{% endif %}</span>
        </div>
        <div class="scorechip scorechip--lc0">
          <span class="scorechip__k">LC0</span>
          <span class="scorechip__v{% if lc0_delta_pct < 0 %} bad{% endif %}">{% if lc0_delta_pct != None %}{{ lc0_delta_pct|stringformat:"+d" }}%{% else %}—{% endif %}</span>
        </div>
      </div>
    </div>
  </div>
  {% endif %}
</section>
```

(`stringformat:"+.2f"` forces a leading sign, e.g. `+0.55` / `-0.45`; `+d` gives `+4` / `-7`. Negative checks `< 0` are false for `None`, so the `bad` class is only added for real negatives.)

- [ ] **Step 2: Sync `#move-chips` to the live ply**

In `services/app/templates/games/analysis.html`, replace the `#move-chips` div:

```django
  <div id="move-chips" style="margin-bottom:24px;"
       hx-get="/_partials/games/{{ game.slug }}/chips/?ply={{ initial_ply }}"
       hx-trigger="load, ply-change from:body"
       hx-include="[name='ply']" hx-swap="innerHTML"></div>
```

with:

```django
  <div id="move-chips" style="margin-bottom:24px;"
       hx-get="/_partials/games/{{ game.slug }}/chips/"
       hx-trigger="load, ply-change from:body"
       hx-vals='js:{ply: (window.WoodLeagueAnalysis && WoodLeagueAnalysis.getState().ply) || 0}'
       hx-swap="innerHTML"></div>
```

- [ ] **Step 3: Add the card layout + score-Δ chip CSS**

In `services/app/static/css/main.css`, insert before the `@layer components` closing `}` (last line):

```css

  /* ── THIS MOVE card (#208) ─────────────────────────────────────────────── */
  .this-move { display: flex; gap: 1rem; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; }
  .this-move__main { flex: 1; min-width: 240px; }
  .this-move__ident { font-family: var(--font-serif); font-size: 1rem; color: var(--color-ebony); margin: 0 0 0.5rem; }
  .this-move__ident b, .this-move__ident { font-weight: 600; }
  .this-move__side { font-family: var(--font-mono); font-size: 0.62rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--color-rust); margin-left: 0.4rem; }
  .this-move__lbl { font-family: var(--font-mono); font-size: 0.55rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-peat); margin: 0 0 0.4rem; }
  .this-move__lbl--c { text-align: center; }
  .this-move__empty { font-family: var(--font-mono); font-size: 0.75rem; color: var(--color-peat); opacity: 0.7; padding: 0.4rem 0 0.2rem; }
  .scorechips { display: flex; gap: 0.5rem; }
  .scorechip { display: flex; flex-direction: column; align-items: center; min-width: 64px; background: var(--color-parchment); border: 1px solid color-mix(in srgb, var(--color-peat) 25%, transparent); }
  .scorechip__k { font-family: var(--font-mono); font-size: 0.5rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-parchment); width: 100%; text-align: center; padding: 1px 0; }
  .scorechip--sf .scorechip__k { background: var(--color-tobacco); }
  .scorechip--lc0 .scorechip__k { background: var(--color-denim); }
  .scorechip__v { font-family: var(--font-serif); font-size: 1.05rem; font-weight: 700; color: var(--color-ebony); padding: 2px 8px 4px; font-variant-numeric: tabular-nums; }
  .scorechip__v.bad { color: var(--color-vermilion-bright); }
```

- [ ] **Step 4: Run the card tests to verify they pass**

Run: `cd services/app && pytest games/tests/test_partial_routes.py -v`
Expected: PASS — including `test_this_move_partial_has_identity_and_score_deltas` (from Task 2) and the existing chip tests.

- [ ] **Step 5: Commit**

```bash
git add services/app/templates/games/partials/_move_chips.html services/app/templates/games/analysis.html services/app/static/css/main.css
git commit -m "feat(#208): THIS MOVE first-class card (layout B) + live ply sync"
```

(Chip tiles + card look + sync are live-reviewed after the Task 6 rebuild.)

---

## Task 4: Plumb LC0 per-candidate + raw played WDL onto `Lc0MoveRow` (F2 data)

**Files:**
- Modify: `services/app/games/services_v2.py` (`Lc0MoveRow` dataclass + its loader, ~lines 119, 205-210)
- Modify: `services/app/games/tests/conftest.py` (`_make_lc0_move_row` — set per-candidate WDL)
- Test: `services/app/games/tests/test_services_v2.py`

The model `Lc0MoveAnalysis` has raw played `wdl_win/draw/loss` and per-candidate `wdl_win_1/2/3`, `wdl_draw_1/2/3`, `wdl_loss_1/2/3`, but `Lc0MoveRow` doesn't carry them. Add them so `board_builder` (Task 5) can compute per-candidate μ.

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_services_v2.py`:

```python
def test_lc0_move_row_carries_raw_and_candidate_wdl(new_schema_game_factory):
    """Lc0MoveRow exposes raw played WDL and per-candidate WDL triples for arrows.

    Parameters:
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    from games.services_v2 import get_game_analysis_v2
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    row = next(m for m in data.lc0_moves if m.ply == 1)
    # raw played triple present
    assert row.wdl_win is not None and row.wdl_draw is not None and row.wdl_loss is not None
    # per-candidate tier-1 triple present
    assert row.wdl_win_1 is not None and row.wdl_draw_1 is not None and row.wdl_loss_1 is not None
```

(If `test_services_v2.py` lacks `new_schema_game_factory`, copy the fixture import/usage from the other v2 tests in that file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/app && pytest games/tests/test_services_v2.py::test_lc0_move_row_carries_raw_and_candidate_wdl -v`
Expected: FAIL (`AttributeError`/`None` — fields not on the dataclass or not loaded).

- [ ] **Step 3: Add the fields to `Lc0MoveRow`**

In `services/app/games/services_v2.py`, add to the `Lc0MoveRow` dataclass (after `wdl_loss_adj`, keep all as optional ints defaulting None):

```python
    # Raw played WDL triple (mover frame, milli-units) — for arrow delta baselines.
    wdl_win: int | None = None
    wdl_draw: int | None = None
    wdl_loss: int | None = None
    # Raw per-candidate WDL triples (mover frame) for the top-3 arrows.
    wdl_win_1: int | None = None
    wdl_draw_1: int | None = None
    wdl_loss_1: int | None = None
    wdl_win_2: int | None = None
    wdl_draw_2: int | None = None
    wdl_loss_2: int | None = None
    wdl_win_3: int | None = None
    wdl_draw_3: int | None = None
    wdl_loss_3: int | None = None
```

(If `Lc0MoveRow` is a frozen/ordered dataclass where earlier fields are non-default, place these after the last existing default-valued field to avoid "non-default after default" errors; verify by reading the class.)

- [ ] **Step 4: Populate them in the loader**

In `services/app/games/services_v2.py`, in the `Lc0MoveRow(...)` construction (~line 205), add the new kwargs read from the model row `r`:

```python
            wdl_win=r.wdl_win, wdl_draw=r.wdl_draw, wdl_loss=r.wdl_loss,
            wdl_win_1=r.wdl_win_1, wdl_draw_1=r.wdl_draw_1, wdl_loss_1=r.wdl_loss_1,
            wdl_win_2=r.wdl_win_2, wdl_draw_2=r.wdl_draw_2, wdl_loss_2=r.wdl_loss_2,
            wdl_win_3=r.wdl_win_3, wdl_draw_3=r.wdl_draw_3, wdl_loss_3=r.wdl_loss_3,
```

- [ ] **Step 5: Populate them in the LC0 fixture**

In `services/app/games/tests/conftest.py`, in `_make_lc0_move_row`'s `Lc0MoveAnalysis.objects.create(...)`, add raw played + per-candidate WDL so the arrow-delta tests (Task 5) have data. Use the played triple as the raw played WDL and simple distinct candidate triples:

```python
        wdl_win=win_adj, wdl_draw=draw_adj, wdl_loss=loss_adj,
        wdl_win_1=win_adj + 40, wdl_draw_1=draw_adj - 20, wdl_loss_1=loss_adj - 20,
        wdl_win_2=win_adj, wdl_draw_2=draw_adj, wdl_loss_2=loss_adj,
        wdl_win_3=win_adj - 40, wdl_draw_3=draw_adj + 20, wdl_loss_3=loss_adj + 20,
```

(Find the exact `Lc0MoveAnalysis.objects.create(` call in `_make_lc0_move_row` and add these kwargs; keep existing kwargs.)

- [ ] **Step 6: Run test + bandit**

Run: `cd services/app && pytest games/tests/test_services_v2.py::test_lc0_move_row_carries_raw_and_candidate_wdl -v` → PASS.
Run: `cd services/app && bandit -ll games/services_v2.py` → no Medium/High.

- [ ] **Step 7: Commit**

```bash
git add services/app/games/services_v2.py services/app/games/tests/conftest.py services/app/games/tests/test_services_v2.py
git commit -m "feat(#208): carry raw + per-candidate LC0 WDL on Lc0MoveRow"
```

---

## Task 5: Arrow labels become delta-vs-played for both engines (F2)

**Files:**
- Modify: `services/app/games/board_builder.py` (`_arrow_entries_from_row`; `_arrow_label` docstring)
- Test: `services/app/games/tests/test_arrow_labels.py`

The arrow `label` becomes the candidate's signed delta vs the move actually played:
- **SF:** `_mover_relative_score(arrow_cp_{tier} − row.cp_eval, is_white_move) / 100` → pawns.
- **LC0:** `μ_cand_{tier} − μ_played` (raw mover-frame WDL, μ = (win + draw/2)/1000), as win-% → `× 100`.

`_arrow_label("sf", value, None)` already formats `value/100` with a sign; `_arrow_label("lc0", None, value)` already formats `value*100` with a sign. So pass the **deltas** as those inputs.

- [ ] **Step 1: Update the tests (characterization of the new contract)**

Replace the two tests in `services/app/games/tests/test_arrow_labels.py` with delta-based assertions. The SF fixture row has `cp_eval=34.0`, `arrow_cp_1=34.0` → SF delta = (34−34)/100 = `+0.00`; add an explicit non-zero case. For LC0 use the per-candidate WDL added in Task 4.

```python
from games.board_builder import build_board_frames, _UNICODE_MINUS
from games.services_v2 import SfMoveRow, Lc0MoveRow


def test_sf_arrow_label_is_delta_vs_played(simple_pgn_game):
    """SF arrow label is the candidate's mover-relative cp delta vs the played move, in pawns.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=65.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    # ply 1 is White's move; delta = (65 - 20)/100 = +0.45
    assert arrow["label"] == "+0.45"


def test_lc0_arrow_label_is_delta_vs_played(simple_pgn_game):
    """LC0 arrow label is the candidate's mover-relative win% delta vs the played move.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    # played mu = (500 + 200/2)/1000 = 0.60 ; candidate1 mu = (620 + 180/2)/1000 = 0.71
    # delta = +0.11 -> +11%
    lc0 = [Lc0MoveRow(
        ply=1, san="e4", fen="", wdl_win_adj=None, wdl_draw_adj=None, wdl_loss_adj=None,
        wdl_mu=None, delta_mu=None, delta_d=None, base_severity="best", draw_character=None,
        best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
        wdl_win=500, wdl_draw=200, wdl_loss=300,
        wdl_win_1=620, wdl_draw_1=180, wdl_loss_1=200,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=[], lc0_moves=lc0, orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == "+11%"
    assert "Lc0" not in arrow["label"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && pytest games/tests/test_arrow_labels.py -v`
Expected: FAIL (SF still shows absolute cp `+0.65`; LC0 still empty/uses row delta_mu).

- [ ] **Step 3: Compute per-candidate deltas in `_arrow_entries_from_row`**

In `services/app/games/board_builder.py`, replace `_arrow_entries_from_row` so each engine builds a per-candidate delta. Read the current function first; the new body:

```python
def _arrow_entries_from_row(engine_key: str, row: object, is_white_move: bool) -> list[dict]:
    """
    Extract flat arrow metadata dicts from a single analysis row.

    Each arrow's ``label`` is the candidate's signed delta vs the move actually
    played, mover-relative: SF as a pawn delta (candidate cp − played cp), LC0 as
    a win-% delta (candidate expected-score μ − played μ from raw WDL triples).

    Params:
        engine_key    (str):    "sf" or "lc0".
        row           (object): SfMoveRow or Lc0MoveRow instance.
        is_white_move (bool):   True when the mover for this ply is White.

    Returns:
        List of arrow dicts, each containing: engine, uci, tier, label.
    """
    ucis = [
        getattr(row, "arrow_uci_1", None),
        getattr(row, "arrow_uci_2", None),
        getattr(row, "arrow_uci_3", None),
    ]
    entries: list[dict] = []
    for tier_index, uci in enumerate(ucis):
        if not (uci and len(uci) >= 4):
            continue
        if engine_key == "sf":
            cand_cp = getattr(row, f"arrow_cp_{tier_index + 1}", None)
            played_cp = getattr(row, "cp_eval", None)
            label = ""
            if cand_cp is not None and played_cp is not None:
                delta_mover = _mover_relative_score(cand_cp - played_cp, is_white_move)
                label = _arrow_label("sf", delta_mover, None)
        else:
            delta_mu = _lc0_candidate_delta_mu(row, tier_index + 1)
            label = _arrow_label("lc0", None, delta_mu)
        entries.append({
            "engine": engine_key,
            "uci": uci,
            "tier": tier_index + 1,
            "label": label,
        })
    return entries
```

And add the LC0 helper above it:

```python
def _wdl_mu(win: int | None, draw: int | None, loss: int | None) -> float | None:
    """Expected-score fraction (0..1) from a milli-unit WDL triple, or None."""
    if win is None or draw is None or loss is None:
        return None
    total = win + draw + loss
    if total <= 0:
        return None
    return (win + (draw / 2.0)) / total


def _lc0_candidate_delta_mu(row: object, tier: int) -> float | None:
    """Candidate-tier expected-score delta vs the played move (mover frame), or None.

    Uses the raw per-candidate WDL (``wdl_*_{tier}``) and raw played WDL
    (``wdl_win/draw/loss``), both mover-frame, so a candidate better for the
    mover reads positive.
    """
    cand = _wdl_mu(
        getattr(row, f"wdl_win_{tier}", None),
        getattr(row, f"wdl_draw_{tier}", None),
        getattr(row, f"wdl_loss_{tier}", None),
    )
    played = _wdl_mu(
        getattr(row, "wdl_win", None),
        getattr(row, "wdl_draw", None),
        getattr(row, "wdl_loss", None),
    )
    if cand is None or played is None:
        return None
    return cand - played
```

(Note: `_wdl_mu` divides by the triple's own total rather than a fixed 1000, so it is robust to rounding; for the test values total=1000 so results match the hand-computed deltas.)

- [ ] **Step 4: Run tests + bandit + grade**

Run: `cd services/app && pytest games/tests/test_arrow_labels.py -v` → PASS.
Run: `cd services/app && bandit -ll games/board_builder.py` → no Medium/High.
Run: `cd services/app && radon cc games/board_builder.py -s | grep -E "_arrow_entries_from_row|_lc0_candidate_delta_mu|_wdl_mu"` → grade B or better.

- [ ] **Step 5: Commit**

```bash
git add services/app/games/board_builder.py services/app/games/tests/test_arrow_labels.py
git commit -m "feat(#208): arrow labels are delta-vs-played for SF (pawns) and LC0 (win%)"
```

- [ ] **Step 6: Live-review note (sign/frame confirmation)**

Because the SF `cp_eval` frame and the LC0 raw-WDL frame are confirmed only by these fixture tests, the implementer must flag for the human live review: open a position with a known good and a known bad alternative and confirm the signs read intuitively (a clearly better candidate is positive for the side to move, both engines). If a sign is inverted on real data, the fix is localized to the `_mover_relative_score` call (SF) or the `cand - played` order (LC0).

---

## Task 6: Tailwind rebuild + full verification

**Files:**
- Modify: `services/app/static/css/tailwind.css` (rebuilt under Node 22)

- [ ] **Step 1: Rebuild Tailwind under Node 22**

```bash
cd services/app
NODE22BIN="$(npx -y node@22 -e 'process.stdout.write(require("path").dirname(process.execPath))')"
PATH="$NODE22BIN:$PATH" bin/build_tailwind.sh
git -C .. diff --stat services/app/static/css/tailwind.css
```

- [ ] **Step 2: Confirm new rules compiled in**

Run: `cd services/app && grep -o "arrow-tg\|this-move\|scorechip" static/css/tailwind.css | sort -u`
Expected: `arrow-tg`, `scorechip`, `this-move` all present.

- [ ] **Step 3: Commit the artifact**

```bash
git add services/app/static/css/tailwind.css
git commit -m "build(#208): rebuild tailwind.css for toggle + THIS MOVE card styles (Node 22)"
```

- [ ] **Step 4: Run the full relevant suite**

```bash
cd services/app && pytest games/tests/test_partial_routes.py games/tests/test_arrow_labels.py games/tests/test_view_game_analysis_shell.py games/tests/test_services_v2.py games/tests/test_chip_data.py -q
```

Expected: all PASS.

- [ ] **Step 5: Final live review**

Run the app from the worktree (`DEBUG=True AUTH_ENABLED=True`) and confirm:
- POSITION header shows the three toggle chips (SF/LC0 on, Best-only off); toggling hides/shows the matching arrows + their labels; Best-only limits to tier-1.
- Board arrows (both engines) show signed delta tags at their bases, drawn on top, non-overlapping; LC0 (blue) arrows now have labels; signs read intuitively.
- THIS MOVE is a card: `Move N · ♔ Side · player`, quality chips as form-2 tiles (parchment tile + engine top-rule, not raw text), and SF/LC0 score-Δ chips on the right (red on a loss); it updates as you navigate the board; ply 0 shows the start-position state.

- [ ] **Step 6: Update the issue + memory**

```bash
gh issue comment 208 --body "THIS MOVE promoted to a first-class synced card (move identity + quality chips + SF/LC0 score-Δ chips); added SF/LC0/best-line arrow toggle controls; arrow labels are now delta-vs-played for both engines (LC0 per-candidate WDL plumbed). Pending live review."
```

Update `project_208_analysis_restyle` memory: note the THIS MOVE card, arrow controls, and delta-vs-played labels are implemented (pending live review); remaining = charts / PGN / hero.

---

## Self-review notes

- **Spec coverage:** F1 controls (T1) ✓; F2 arrow delta-vs-played both engines + LC0 WDL plumbing (T4, T5) ✓; F3 first-class card + identity + score-Δ + ply sync (T2, T3) ✓; F4 form-2 chip tiles (T3 markup + T6 rebuild) ✓; rebuild last (T6) ✓; charts/PGN/hero out of scope ✓.
- **Placeholder scan:** concrete code in every step. Two grep-confirm steps (T2 `white_label`, T4 field-order) are verification, not placeholders.
- **Type/name consistency:** `_this_move_context` returns `move_no/side/king_sym/move_label/sf_delta_pawns/lc0_delta_pct`, all consumed by the same names in `_move_chips.html` (T3). `_lc0_candidate_delta_mu`/`_wdl_mu` defined and used in T5. `Lc0MoveRow` WDL fields added in T4 are read in T5 via `getattr(row, "wdl_win_{tier}")`. Arrow `label` contract (signed delta string) consistent between T5 producer and `test_arrow_labels.py`.
- **Frame risk:** SF `cp_eval` frame and LC0 raw-WDL frame are locked by fixture tests (T2, T5) and flagged for human sign-confirmation (T5 Step 6) — the documented residual risk from the spec.
