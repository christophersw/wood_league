# Board Builder v2 Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual-signature `build_board_frames` and parallel v1/v2 service layers with one end-to-end v2 path; live LC0 arrow labels render as a side effect.

**Architecture:** Service layer exposes typed dataclasses (`SfMoveRow`, `Lc0MoveRow`) via `load_board_inputs(game)`. Board builder accepts those + PGN, returns self-contained frame dicts (`{svg, arrows, ply, san, last_move_uci, classification}`) with tightened per-arrow shape (`{engine, uci, tier, label, color, opacity}`). View, template, and JS all migrate atomically; legacy branch + v1 `services.py` surface are deleted.

**Tech Stack:** Python 3.13 + Django, HTMX, hand-written JS in `_board_partial.html`, pytest+coverage gate (ruff → bandit + semgrep → radon/xenon → mypy → pytest+cov).

**Spec:** `docs/superpowers/specs/2026-05-25-board-builder-v2-consolidation-design.md`

**Worktree:** `/Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+209-board-builder-v2/`
**Branch:** `issue/209-consolidate-build-board-frames-v2-signature` (off `main`)
**Venv (REPO ROOT, not services/app):** `source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate` then `cd services/app` for all test/lint commands.

---

## Task 1: Pre-cutover audit

Document three facts the spec calls out as risks but doesn't pin down. Output is a short markdown file in `docs/superpowers/notes/` that the cutover tasks reference. No production code changes.

**Files:**
- Create: `docs/superpowers/notes/2026-05-26-209-cutover-audit.md`

- [ ] **Step 1: Audit `services.py` consumers**

Run from the worktree's `services/app/`:

```bash
grep -rn "from games.services\b\|from games import services\b\|games\.services\." \
  --include="*.py" .. 2>/dev/null \
  | grep -v __pycache__ | grep -v "services_v2"
```

Expected hits (from the spec's pre-audit): `games/board_builder.py:49`, `games/tests.py:20`, `games/views.py:44`. Record every actual hit in the notes file. **Any hit outside those three files must be called out** — it means another consumer needs migrating before `services.py` can be deleted.

- [ ] **Step 2: Audit `stroke_width` usage in the JS**

```bash
grep -n "stroke_width\|strokeWidth\|stroke-width" \
  templates/games/_board_partial.html \
  static/games/*.js 2>/dev/null
```

Record every hit. If the JS reads `arrowData.stroke_width` (or `strokeWidth`), Task 4's tightened arrow dict must keep the `stroke_width` key; if not, it's dropped per spec.

- [ ] **Step 3: Audit engine-line handler attribute reads**

Read `games/views.py` lines 395–470 (the engine-line handler + `_engine_line_bot_label` + `_engine_line_player_meta`). Record every attribute read off `data:` (e.g. `data.engine_depth`, `data.sf_nodes`, `data.lc0_nodes`, `data.has_sf`, `data.has_lc0`, etc.).

Then read `games/services_v2.py` (`GameAnalysisDataV2` class + `_apply_sf_summary` + `_apply_lc0_summary`) and confirm every attribute in the list above is set on the v2 dataclass. **Any v1-only attribute is a real surprise** — Task 9 will need to extend the v2 applier to populate it (not paper over with `getattr` defaults).

- [ ] **Step 4: Write the notes file**

Single markdown file with three sections (`## services.py consumers`, `## stroke_width usage`, `## Engine-line attributes`), each containing the raw findings from steps 1–3 plus a one-line **verdict** per section (e.g. "✅ matches spec / ⚠️ unexpected: …"). Keep terse; this is a reference for the cutover, not prose.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/2026-05-26-209-cutover-audit.md
git commit -m "$(printf '%s\n' \
  'docs(#209): cutover audit — services.py consumers, stroke_width, engine-line attrs' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: Tighten v2 arrow-entry shape (add `color`, `opacity`)

`_arrow_entries_from_row` today emits `{engine, uci, tier, label}`. Per spec it must emit `{engine, uci, tier, label, color, opacity}`. Drop nothing else from this dict yet — frame-level reshape happens in Task 3.

**Files:**
- Modify: `services/app/games/board_builder.py` (`_arrow_entries_from_row` around line 538)
- Modify: `services/app/games/tests/test_arrow_labels.py` (assertions)

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_arrow_labels.py`:

```python
def test_v2_arrow_entry_has_color_and_opacity(simple_pgn_game):
    """Each v2 arrow entry carries an engine colour and a delta-encoded opacity.

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
    assert isinstance(arrow["color"], str) and arrow["color"].startswith("#"), arrow
    assert 0.42 <= arrow["opacity"] <= 0.98, arrow
```

- [ ] **Step 2: Run test to verify it fails**

```bash
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+209-board-builder-v2/services/app
pytest games/tests/test_arrow_labels.py::test_v2_arrow_entry_has_color_and_opacity -v
```

Expected: FAIL with `KeyError: 'color'`.

- [ ] **Step 3: Extend `_arrow_entries_from_row` to emit `color` + `opacity`**

In `games/board_builder.py`, replace `_arrow_entries_from_row` (around line 538) with:

```python
def _arrow_entries_from_row(engine_key: str, row: object, is_white_move: bool) -> list[dict]:
    """
    Extract flat arrow metadata dicts from a single analysis row.

    Each arrow's ``label`` is the candidate's signed delta vs the move actually
    played, mover-relative: SF as a pawn delta (candidate cp - played cp), LC0 as
    a win-% delta (candidate expected-score mu - played mu from raw WDL triples).

    Each arrow also carries ``color`` (engine base hex) and ``opacity`` (encoding
    tier rank and delta magnitude); the client uses these directly without further
    derivation.

    Params:
        engine_key    (str):    "sf" or "lc0".
        row           (object): SfMoveRow or Lc0MoveRow instance.
        is_white_move (bool):   True when the mover for this ply is White.

    Returns:
        List of arrow dicts: {engine, uci, tier, label, color, opacity}.
    """
    ucis = [
        getattr(row, "arrow_uci_1", None),
        getattr(row, "arrow_uci_2", None),
        getattr(row, "arrow_uci_3", None),
    ]
    base_color = _ENGINE_BASE_COLORS[engine_key]
    entries: list[dict] = []
    for tier_index, uci in enumerate(ucis):
        if not (uci and len(uci) >= 4):
            continue
        if engine_key == "sf":
            cand_cp = getattr(row, f"arrow_cp_{tier_index + 1}", None)
            played_cp = getattr(row, "cp_eval", None)
            label = ""
            delta_for_opacity: float | None = None
            if cand_cp is not None and played_cp is not None:
                delta_mover = _mover_relative_score(cand_cp - played_cp, is_white_move)
                label = _arrow_label("sf", delta_mover, None)
                delta_for_opacity = delta_mover
        else:
            delta_mu = _lc0_candidate_delta_mu(row, tier_index + 1)
            label = _arrow_label("lc0", None, delta_mu)
            # Scale mu delta (unit: 0..1) into cp-equivalent for opacity shading.
            delta_for_opacity = (delta_mu * 100.0) if delta_mu is not None else None
        entries.append({
            "engine": engine_key,
            "uci": uci,
            "tier": tier_index + 1,
            "label": label,
            "color": base_color,
            "opacity": _build_arrow_opacity(delta_for_opacity, tier_index),
        })
    return entries
```

- [ ] **Step 4: Run targeted tests**

```bash
pytest games/tests/test_arrow_labels.py -v
```

Expected: all tests in the file PASS (existing four + the new color/opacity test).

- [ ] **Step 5: Commit**

```bash
git add games/board_builder.py games/tests/test_arrow_labels.py
git commit -m "$(printf '%s\n' \
  'feat(#209): v2 arrow entries carry engine color + delta-encoded opacity' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: Self-contained v2 frames (`svg`, `ply`, `san`, `last_move_uci`, `classification`)

Today the v2 frame-building loop emits frames that have `arrows` but not the full set the spec requires. Extend the loop so each frame is self-describing.

**Files:**
- Modify: `services/app/games/board_builder.py` (v2 frame loop, the function that handles the `pgn=…, sf_moves=…, lc0_moves=…` signature — search for `_arrow_entries_from_row` call sites around line 433–435 and walk up to the enclosing loop)
- Modify: `services/app/games/tests/test_board_builder_ply_alignment.py`

- [ ] **Step 1: Locate the v2 frame loop and read it**

```bash
grep -n "_arrow_entries_from_row\|def build_board_frames\|def _v2\|frames\[" \
  games/board_builder.py | sed -n '1,40p'
```

Read the v2 frame loop's current body (the function called from the new-signature branch of `build_board_frames`). Confirm what each frame dict currently contains; the cutover will *add* keys, not remove anything the v2 tests already assert.

- [ ] **Step 2: Write the failing test**

Add to `services/app/games/tests/test_board_builder_ply_alignment.py`:

```python
def test_v2_frames_are_self_contained(simple_pgn_game):
    """Every v2 frame carries svg, ply, san, last_move_uci, classification.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0,
        move_win_delta=0.0, classification="best", best_move="",
        arrow_uci_1=None, arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=None, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(
        pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white",
    )["frames"]
    # Ply 0 = start position; san and last_move_uci must be None there.
    assert frames[0]["ply"] == 0
    assert frames[0]["san"] is None
    assert frames[0]["last_move_uci"] is None
    assert frames[0]["classification"] is None
    assert isinstance(frames[0]["svg"], str) and frames[0]["svg"].startswith("<svg")
    # Ply 1 = first move; san + last_move_uci + classification populated from SF.
    assert frames[1]["ply"] == 1
    assert frames[1]["san"] == "e4"
    assert frames[1]["last_move_uci"] == "e2e4"
    assert frames[1]["classification"] == "best"
    assert isinstance(frames[1]["svg"], str) and frames[1]["svg"].startswith("<svg")
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest games/tests/test_board_builder_ply_alignment.py::test_v2_frames_are_self_contained -v
```

Expected: FAIL with `KeyError: 'svg'` (or `'ply'`, whichever the current frame dict is missing first).

- [ ] **Step 4: Extend the v2 frame loop**

Inside the v2 frame loop, for each frame dict (start position + per-ply), emit:

```python
frame = {
    "svg": rendered_svg_string,        # already rendered for tinting via classification colors
    "arrows": arrow_entries_for_this_ply,
    "ply": ply_index,                  # 0 for start position
    "san": san_for_this_ply,           # None when ply == 0
    "last_move_uci": uci_for_this_ply, # None when ply == 0; 4-char UCI otherwise
    "classification": sf_row.classification if sf_row is not None else None,
}
```

The SVG rendering call already exists in the v2 loop (or matches the legacy one) — reuse the same renderer + the same `board_colors_for_move_classification(classification)` tinting helper for last-move squares. `san_for_this_ply` comes from `chess.Board.san(move)` against the parent position (the loop is already iterating the PGN; pull san from there). `uci_for_this_ply` = `move.uci()`. `classification` is read off the SF row for this ply when present, else None.

- [ ] **Step 5: Run targeted tests**

```bash
pytest games/tests/test_board_builder_ply_alignment.py games/tests/test_arrow_labels.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add games/board_builder.py games/tests/test_board_builder_ply_alignment.py
git commit -m "$(printf '%s\n' \
  'feat(#209): v2 frames are self-contained (svg, ply, san, last_move_uci, classification)' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: v2 top-level keys (`overlay_geometry`, `player_layout`, `has_sf`, `has_lc0`)

The view template reads these top-level keys today off the legacy result. The v2 result must provide them so the template doesn't change shape between paths.

**Files:**
- Modify: `services/app/games/board_builder.py` (the v2 branch of `build_board_frames`)
- Modify: `services/app/games/tests/test_board_builder_ply_alignment.py`

- [ ] **Step 1: Write the failing test**

Add to `services/app/games/tests/test_board_builder_ply_alignment.py`:

```python
def test_v2_result_has_top_level_keys(simple_pgn_game):
    """v2 build_board_frames returns overlay_geometry, player_layout, has_sf, has_lc0.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0,
        move_win_delta=0.0, classification="best", best_move="",
        arrow_uci_1=None, arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=None, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    result = build_board_frames(
        pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white", size=480,
    )
    assert "overlay_geometry" in result
    assert {"viewbox_size", "board_margin", "square_size"} <= set(result["overlay_geometry"].keys())
    assert "player_layout" in result
    assert {"top_side", "bottom_side"} <= set(result["player_layout"].keys())
    assert result["has_sf"] is True
    assert result["has_lc0"] is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest games/tests/test_board_builder_ply_alignment.py::test_v2_result_has_top_level_keys -v
```

Expected: FAIL with `AssertionError` on one of the four `in` / boolean checks (whichever the v2 path is missing).

- [ ] **Step 3: Populate the missing top-level keys in the v2 branch**

In `games/board_builder.py`, in the v2 branch of `build_board_frames`, before returning:

```python
return {
    "frames": frames,
    "overlay_geometry": _board_overlay_geometry(size),
    "player_layout": _v2_player_layout(pgn, orientation),
    "has_sf": bool(sf_moves),
    "has_lc0": bool(lc0_moves),
}
```

`_board_overlay_geometry` already exists (legacy code, reused). Add a tiny `_v2_player_layout(pgn, orientation)` helper if the existing `_player_layout(data, flipped)` legacy helper can't be reused directly — it should return `{"top_side": "White" | "Black", "bottom_side": "White" | "Black", "top_name": str | None, "bottom_name": str | None}` based on PGN headers + orientation. Names from PGN headers if present; None otherwise. Keep it under 10 lines (it's bookkeeping).

- [ ] **Step 4: Run targeted tests**

```bash
pytest games/tests/test_board_builder_ply_alignment.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add games/board_builder.py games/tests/test_board_builder_ply_alignment.py
git commit -m "$(printf '%s\n' \
  'feat(#209): v2 result exposes overlay_geometry, player_layout, has_sf, has_lc0' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 5: `load_board_inputs(game)` in `services_v2.py`

Thin loader: `Game` → `(pgn, sf_moves, lc0_moves)`. Wraps existing v2 internals so the view becomes a one-liner.

**Files:**
- Modify: `services/app/games/services_v2.py` (append public function near `get_game_analysis_v2`)
- Create: `services/app/games/tests/test_load_board_inputs.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/games/tests/test_load_board_inputs.py`:

```python
"""
Title: test_load_board_inputs.py — Tests for services_v2.load_board_inputs
Description:
    Verifies that load_board_inputs returns a (pgn, sf_moves, lc0_moves) triple
    suitable for build_board_frames, including the empty-engine and no-analysis
    cases.

Changelog:
    2026-05-26 (#209): Initial — supports board_builder v2 cutover.
"""
import pytest
from games.services_v2 import SfMoveRow, Lc0MoveRow, load_board_inputs

pytestmark = pytest.mark.django_db


def test_load_board_inputs_returns_pgn_and_typed_lists(simple_pgn_game):
    """Returns the game's PGN plus typed dataclass lists for each engine."""
    pgn, sf_moves, lc0_moves = load_board_inputs(simple_pgn_game)
    assert isinstance(pgn, str) and pgn.startswith("[")  # PGN header bracket
    assert all(isinstance(r, SfMoveRow) for r in sf_moves)
    assert all(isinstance(r, Lc0MoveRow) for r in lc0_moves)


def test_load_board_inputs_no_analysis_returns_empty_engine_lists(pgn_only_game):
    """Games without engine analysis yield empty engine lists, never None."""
    pgn, sf_moves, lc0_moves = load_board_inputs(pgn_only_game)
    assert pgn
    assert sf_moves == []
    assert lc0_moves == []
```

If `pgn_only_game` isn't an existing fixture, add one to `services/app/games/tests/conftest.py` modelled after `simple_pgn_game` but with no related `GameAnalysis` / `Lc0GameAnalysis` records. Check conftest.py first; if `simple_pgn_game` already has no analyses, drop the second test.

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest games/tests/test_load_board_inputs.py -v
```

Expected: FAIL with `ImportError: cannot import name 'load_board_inputs'`.

- [ ] **Step 3: Implement `load_board_inputs`**

Append to `services/app/games/services_v2.py`:

```python
def load_board_inputs(game: Game) -> tuple[str, list[SfMoveRow], list[Lc0MoveRow]]:
    """Return (pgn, sf_moves, lc0_moves) for the analysis-page board builder.

    Wraps the v2 analysis loaders so view code doesn't need to know about
    GameAnalysis / Lc0GameAnalysis lookups or row construction.

    Params:
        game (Game): The Django Game model row to render.

    Returns:
        tuple[str, list[SfMoveRow], list[Lc0MoveRow]]:
            - pgn: The game's PGN string (always present; empty string if the
              Game has no pgn field set, though that should not happen in practice).
            - sf_moves: Stockfish move rows, or [] when no SF analysis exists.
            - lc0_moves: LC0 move rows, or [] when no LC0 analysis exists.
    """
    ga, lga = _load_analyses(game)
    return (game.pgn or "", _sf_rows(ga), _lc0_rows(lga))
```

- [ ] **Step 4: Run targeted tests**

```bash
pytest games/tests/test_load_board_inputs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add games/services_v2.py games/tests/test_load_board_inputs.py services/app/games/tests/conftest.py 2>/dev/null || true
git add -A games/services_v2.py games/tests/
git commit -m "$(printf '%s\n' \
  'feat(#209): add services_v2.load_board_inputs(game) — view-facing loader' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 6: Analysis-view integration test (the missing test that let the bug ship)

End-to-end test that drives the analysis-page view and asserts LC0 arrow labels appear in the rendered HTML's frames JSON. Must fail against current main (legacy path), pass after Task 7's cutover.

**Files:**
- Create: `services/app/games/tests/test_analysis_view_integration.py`

- [ ] **Step 1: Write the failing test**

Create `services/app/games/tests/test_analysis_view_integration.py`:

```python
"""
Title: test_analysis_view_integration.py — End-to-end analysis-view contract
Description:
    Drives the game-analysis page view against a fixture game that has full
    LC0 WDL data, parses the rendered frames JSON, and asserts each engine's
    arrows carry a non-empty label. This is the integration test whose absence
    let the LC0-labels regression ship during #208 live review.

Changelog:
    2026-05-26 (#209): Initial — proves the v2 cutover delivers labels live.
"""
import json
import re
import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _extract_frames_json(html: str) -> list[dict]:
    """Extract the frames JSON script block from the rendered analysis page.

    Params:
        html (str): The rendered HTML response body.

    Returns:
        list[dict]: The parsed frames array.

    Raises:
        AssertionError: If the frames JSON block is not present.
    """
    match = re.search(
        r'<script type="application/json" id="board-frames-json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "board-frames-json script block not found in response"
    return json.loads(match.group(1))


def test_analysis_view_renders_lc0_arrow_labels(client, fully_analysed_game):
    """LC0 arrows in the rendered frames JSON carry non-empty labels.

    Parameters:
        client: Django test client.
        fully_analysed_game: Fixture game with both SF and full LC0 WDL data.
    """
    response = client.get(reverse("game_analysis", kwargs={"slug": fully_analysed_game.slug}))
    assert response.status_code == 200
    frames = _extract_frames_json(response.content.decode())
    lc0_arrows = [
        arrow
        for frame in frames
        for arrow in frame.get("arrows", [])
        if arrow.get("engine") == "lc0"
    ]
    assert lc0_arrows, "no LC0 arrows in any frame — fixture should have them"
    labelled = [a for a in lc0_arrows if a.get("label")]
    assert labelled, f"all {len(lc0_arrows)} LC0 arrows have empty labels — the live bug"


def test_analysis_view_renders_sf_arrow_labels(client, fully_analysed_game):
    """SF arrows in the rendered frames JSON carry non-empty labels.

    Parameters:
        client: Django test client.
        fully_analysed_game: Fixture game with both SF and full LC0 WDL data.
    """
    response = client.get(reverse("game_analysis", kwargs={"slug": fully_analysed_game.slug}))
    assert response.status_code == 200
    frames = _extract_frames_json(response.content.decode())
    sf_arrows = [
        arrow
        for frame in frames
        for arrow in frame.get("arrows", [])
        if arrow.get("engine") == "sf"
    ]
    assert sf_arrows
    assert all(a.get("label") for a in sf_arrows)
```

Confirm the URL name `game_analysis` matches the real URL conf — search `services/app/games/urls.py` and `services/app/config/urls.py` for the analysis-page route and use whichever `name=` it actually carries. Add a `fully_analysed_game` fixture to `services/app/games/tests/conftest.py` modelled on `simple_pgn_game`, but with a related `GameAnalysis` populated with at least one SF row (cp_eval + arrow_cp_1 + arrow_uci_1) and a related `Lc0GameAnalysis` populated with at least one `Lc0MoveAnalysis` row carrying all of `wdl_win/draw/loss`, `wdl_win_1/draw_1/loss_1`, `wdl_win_adj/draw_adj/loss_adj`, and `arrow_uci_1`.

- [ ] **Step 2: Run test to verify it fails against current code**

```bash
pytest games/tests/test_analysis_view_integration.py -v
```

Expected: at minimum `test_analysis_view_renders_lc0_arrow_labels` FAILS (likely either "board-frames-json script block not found" if the legacy template name differs, or "all N LC0 arrows have empty labels" — both are exactly the bug). If the script block name differs (legacy uses `board-arrows-json`), that's expected at this point — Task 7 will rename it. Note the failure mode in the commit message.

- [ ] **Step 3: Commit (red test on purpose)**

```bash
git add games/tests/test_analysis_view_integration.py games/tests/conftest.py
git commit -m "$(printf '%s\n' \
  'test(#209): analysis-view integration test for engine arrow labels' \
  '' \
  'Intentionally red against the legacy path — turns green after Task 7' \
  'cuts the view to the v2 board pipeline.' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 7: Cutover — analysis view + template + JS to v2 (atomic)

This is the riskiest single commit because three files must change together: the view must call the v2 path, the template must emit the new JSON block name + shape, and the JS must read it. Splitting them mid-flight produces a broken page.

**Files:**
- Modify: `services/app/games/views.py` (analysis-page handler at `:209`)
- Modify: `services/app/templates/games/_board_partial.html`

- [ ] **Step 1: Read the current analysis-page view + template + JS**

Read these three regions before editing:

1. `games/views.py` from the function containing line 209 (find the enclosing `def` — likely `def game_analysis` or similar) through its full body.
2. `templates/games/_board_partial.html` lines 1–80 (script blocks + container) and lines 80–end (JS).
3. The current `arrow_data_json` script block name and the JS variable it parses into (`arrowsByPly`).

Note the view's existing context dict keys; the cutover preserves them but swaps the data source.

- [ ] **Step 2: Migrate the view**

In the analysis-page handler, replace:

```python
data = get_game_analysis(slug)
# ... possibly: if data is None: raise Http404 ...
board_data = build_board_frames(data, size=480, orientation=orientation)
```

with:

```python
from games.services_v2 import get_game_analysis_v2, load_board_inputs

data = get_game_analysis_v2(slug)
if data is None:
    raise Http404("game not found")
pgn, sf_moves, lc0_moves = load_board_inputs(data.game)
board_data = build_board_frames(
    pgn, sf_moves, lc0_moves, orientation=orientation, size=480,
)
```

Replace any downstream context-dict references to v1-typed `data` attributes only if mypy or runtime errors surface — most handlers in this view file already consume `GameAnalysisDataV2`, so the same handler likely already uses `get_game_analysis_v2` elsewhere; reuse that path. (If `data.game` is not a v2 attribute, use the URL slug to fetch the Game model directly: `from games.models import Game; game = get_object_or_404(Game, slug=slug); pgn, sf_moves, lc0_moves = load_board_inputs(game)` — adjust to whichever pattern is used by the cards/charts handlers.)

Remove the now-unused `from games.services import ...` import line if nothing else in views.py references it (likely still needed for Task 9; check before deleting).

- [ ] **Step 3: Update the template script block + JS**

In `templates/games/_board_partial.html`:

Replace the existing `<script type="application/json" id="board-arrows-json">{{ arrow_data_json|safe }}</script>` block with:

```django
<script type="application/json" id="board-frames-json">{{ frames_json|safe }}</script>
```

The view context must provide `frames_json = json.dumps(board_data["frames"])`. Add that to the view's context dict in Step 2 (replace the prior `arrow_data_json = json.dumps(arrows_by_ply)` if present).

Update the JS at the top of the same file. Replace:

```javascript
var arrowsByPly = JSON.parse(document.getElementById('board-arrows-json').textContent);
```

with:

```javascript
var frames = JSON.parse(document.getElementById('board-frames-json').textContent);
function arrowsForPly(ply) { return (frames[ply] && frames[ply].arrows) || []; }
function displayEngineName(engine) { return engine === 'lc0' ? 'Lc0' : 'Stockfish'; }
```

Find every other JS reference to `arrowsByPly` (use the IDE search) and replace with `arrowsForPly(ply)`. Inside `buildArrowElement(arrowData, ply, layoutOptions)`:

- Replace `arrowData.from_sq` → `arrowData.uci.slice(0, 2)`.
- Replace `arrowData.to_sq` → `arrowData.uci.slice(2, 4)`.
- Replace `arrowData.move_uci` → `arrowData.uci`.
- Replace any `arrowData.title` consumer with a composed string:
  ```javascript
  var titleText = displayEngineName(arrowData.engine) + ' #' + arrowData.tier + ': ' + arrowData.uci;
  if (arrowData.label) titleText += ' (' + arrowData.label + ')';
  ```
- Replace `arrowData.engine_label` (if read anywhere) with `displayEngineName(arrowData.engine)`.

If the SVG-per-frame string is rendered into the board container by a separate path today (e.g. from `frames` list of SVG strings), update that path to read `frames[currentPly].svg` instead.

- [ ] **Step 4: Run the integration test**

```bash
pytest games/tests/test_analysis_view_integration.py games/tests/test_arrow_labels.py games/tests/test_board_builder_ply_alignment.py games/tests/test_load_board_inputs.py -v
```

Expected: all PASS — Task 6's previously-red integration test now goes green.

- [ ] **Step 5: Full game-tests run**

```bash
pytest games/tests/ -v
```

Expected: all PASS. If anything in the wider game tests breaks (most likely the engine-line characterization tests we shipped in #208), that's expected fallout from changing the analysis-page context — note the failures, do not fix yet; Task 9 handles the engine-line migration.

If the wider game tests still fail after Task 9 lands, return to fix them then. For Task 7 itself, only the four test files above must pass.

- [ ] **Step 6: Commit**

```bash
git add games/views.py templates/games/_board_partial.html
git commit -m "$(printf '%s\n' \
  'feat(#209): cut analysis view + board template/JS to v2 pipeline' \
  '' \
  'View now calls load_board_inputs(game) + build_board_frames(pgn, sf_moves,' \
  'lc0_moves, …). Template emits frames_json (frames-as-dicts with embedded' \
  'arrows). JS reads arrows per-frame and derives from_sq/to_sq/title client-' \
  'side. LC0 arrow labels render live as a side effect.' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 8: Migrate `engine_line_partial` handler to v2

Per the Task 1 audit (`docs/superpowers/notes/2026-05-26-209-cutover-audit.md`): on `main` (this branch's base), the only engine-line code is `engine_line_partial` (~views.py:277) and the `_engine_row_for_request` helper (views.py:97). The `_engine_line_bot_label` / `_engine_line_player_meta` helpers mentioned earlier in the spec are #208 additions and do **not** exist on this branch — drop any instruction to re-type them. The only v1→v2 attribute rename relevant on this branch is `data.moves` → `data.sf_moves` inside `_engine_row_for_request` (line 97).

**Files:**
- Modify: `services/app/games/views.py` (`_engine_row_for_request` at line 97 + `engine_line_partial` around line 277)

- [ ] **Step 1: Run the existing engine-line tests (or skip if none)**

```bash
pytest games/tests/ -v -k engine_line
```

Expected: PASS, or "no tests ran" if no `engine_line` tests live on `main`. (The #208-side characterization tests do not exist on this branch.)

- [ ] **Step 2: Swap the loader call in `engine_line_partial`**

In `games/views.py`, in the function containing the engine-line partial handler (~line 277), replace `data = get_game_analysis(slug)` with `data = get_game_analysis_v2(slug)`. Keep the surrounding `if data is None: ...` 404 guard as-is.

- [ ] **Step 3: Rewrite `_engine_row_for_request` for the v2 attribute name**

In `games/views.py:97`, the function selects move rows based on the requested engine. The current v1 body reads `data.moves` for Stockfish. v2 renames this to `data.sf_moves`. Make exactly that substitution:

```python
# In _engine_row_for_request (services/app/games/views.py:97)
# v1:  rows = data.moves if engine == "sf" else data.lc0_moves
# v2:  rows = data.sf_moves if engine == "sf" else data.lc0_moves
```

Re-type the parameter annotation on `_engine_row_for_request` from `GameAnalysisData` / `MoveRow` to `GameAnalysisDataV2` / `SfMoveRow` (and `Lc0MoveRow` if the function returns either union). Read the function body to confirm whether it returns `MoveRow | None` (legacy) or needs splitting into engine-typed branches — keep the change minimal; only do what mypy demands.

- [ ] **Step 4: Run engine-line tests**

```bash
pytest games/tests/ -v -k engine_line
```

Expected: PASS. If anything fails on AttributeError for a v2-missing attribute, return to Step 3.

- [ ] **Step 5: Run mypy on views.py**

```bash
mypy games/views.py 2>&1 | head -40
```

Expected: no new errors versus the pre-Task-8 baseline. (Run `git stash && mypy games/views.py && git stash pop` if you need to capture the baseline.)

- [ ] **Step 6: Commit**

```bash
git add games/views.py games/services_v2.py 2>/dev/null || git add games/views.py
git commit -m "$(printf '%s\n' \
  'feat(#209): engine-line partial handler reads from v2 service layer' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 9: Re-type remaining v1 view helpers

The small view helpers around lines 88, 108, 402 are typed `data: GameAnalysisData` / `move_row: MoveRow`. Re-type to v2.

**Files:**
- Modify: `services/app/games/views.py` (functions around lines 88, 108, 402 — locate by reading the function defs)

- [ ] **Step 1: List affected helpers**

```bash
grep -n "GameAnalysisData\|MoveRow\b" games/views.py
```

Record each function whose parameter list mentions `GameAnalysisData` or `MoveRow`.

- [ ] **Step 2: Re-type each helper**

For each function on the list:
- Change `GameAnalysisData` annotations to `GameAnalysisDataV2`.
- Change `MoveRow` annotations to `SfMoveRow` (these helpers operate on the SF move stream — verify by reading the function body; if any actually wants Lc0MoveRow, use that instead).
- Update import line at top: `from games.services import GameAnalysisData, MoveRow, get_game_analysis` should be removable entirely once Tasks 7–9 are done. If `get_game_analysis` is still referenced anywhere, that's a missed migration — return to Tasks 7/8.

- [ ] **Step 3: Run mypy**

```bash
mypy games/views.py games/services_v2.py 2>&1 | head -40
```

Expected: no new errors versus baseline. Any attribute mismatch (e.g. `data.foo` exists on v1 but not v2) means extending the v2 applier per Task 8 Step 3.

- [ ] **Step 4: Run the full games test suite**

```bash
pytest games/tests/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add games/views.py games/services_v2.py 2>/dev/null || git add games/views.py
git commit -m "$(printf '%s\n' \
  'refactor(#209): re-type remaining view helpers to v2 service types' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 10: Delete legacy `build_board_frames` branch + `_legacy_*` helpers

`games/views.py` no longer calls the legacy positional signature. Delete it and every helper exclusive to it.

**Files:**
- Modify: `services/app/games/board_builder.py`

- [ ] **Step 1: Confirm no remaining callers of the legacy signature**

```bash
grep -rn "build_board_frames(\s*data\b\|build_board_frames(\s*ga\b" \
  --include="*.py" .
```

Expected: zero hits anywhere except the dead `games/tests.py` (which Task 12 deletes). If any other hit exists, return to Tasks 7–9.

- [ ] **Step 2: Rewrite `build_board_frames` as the single v2 signature**

Replace the dual-routing `build_board_frames` with a single function whose signature is:

```python
def build_board_frames(
    pgn: str,
    sf_moves: list[SfMoveRow],
    lc0_moves: list[Lc0MoveRow],
    *,
    orientation: Literal["white", "black"] = "white",
    size: int = 480,
) -> dict:
    """
    Render board frames + per-frame engine arrows for the analysis page.

    Params:
        pgn (str):                      Game PGN text (may be empty).
        sf_moves (list[SfMoveRow]):     Stockfish move rows, indexed by ply.
        lc0_moves (list[Lc0MoveRow]):   LC0 move rows, indexed by ply.
        orientation (str):              "white" (default) or "black".
        size (int):                     Rendered board pixel size.

    Returns:
        dict: {frames, overlay_geometry, player_layout, has_sf, has_lc0}.
              See the design spec for full shape details.
    """
    # ... body == the existing v2 branch's body, lifted out of the if/else router
```

Delete the legacy positional branch and the dispatch logic. Delete from the same file every helper that was only used by the legacy branch:

- `_build_tier_map`
- `_build_arrow_entries_for_engine`
- `_resolve_tier_entries`
- `_legacy_tier_context`
- `_legacy_frame_loop`
- `_build_single_arrow_entry`
- `_format_arrow_delta`
- `_compute_arrow_delta`
- the legacy `_player_layout(data, flipped)` (keep `_v2_player_layout` added in Task 4)

Keep `_build_arrow_opacity`, `_mover_relative_score`, `_board_overlay_geometry`, `_ENGINE_BASE_COLORS`, `_arrow_label`, `_wdl_mu`, `_lc0_candidate_delta_mu`, `_arrow_entries_from_row`, `board_colors_for_move_classification`.

- [ ] **Step 3: Delete the legacy `from games.services import …` line at top of board_builder.py**

```bash
grep -n "from games.services\b" games/board_builder.py
```

If `GameAnalysisData` / `MoveRow` are imported, they're now dead — remove the import.

- [ ] **Step 4: Run the full games test suite**

```bash
pytest games/tests/ -v
```

Expected: all PASS.

- [ ] **Step 5: Run the static gate**

```bash
ruff check games/board_builder.py
xenon --max-absolute B --max-modules B --max-average A games/board_builder.py
mypy games/board_builder.py
```

Expected: all clean. If xenon flags grade > B on the new unified `build_board_frames`, extract a `_build_frame(...)` helper — do not paper over with `# noqa`.

- [ ] **Step 6: Commit**

```bash
git add games/board_builder.py
git commit -m "$(printf '%s\n' \
  'refactor(#209): drop legacy build_board_frames branch + _legacy_* helpers' \
  '' \
  'Single keyword-only signature: build_board_frames(pgn, sf_moves, lc0_moves,' \
  '*, orientation, size). Calling the old positional shape now raises TypeError.' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 11: Delete `services.py` v1 board surface

After Tasks 7–10, nothing in production reads from `games.services`. Delete the v1 functions; if anything is reused (e.g. by `services_v2`), move it first.

**Files:**
- Modify or delete: `services/app/games/services.py`

- [ ] **Step 1: Confirm no remaining importers**

```bash
grep -rn "from games.services\b\|from games import services\b\|games\.services\." \
  --include="*.py" .. 2>/dev/null \
  | grep -v __pycache__ | grep -v services_v2 | grep -v "games/services.py:"
```

Expected hits: only `games/tests.py` (dead-shadowed, Task 12 deletes). If anything else, fix the missed import before continuing.

- [ ] **Step 2: Check whether `services_v2.py` reuses anything from `services.py`**

```bash
grep -n "from .services\b\|from games.services\b" games/services_v2.py
```

Expected: nothing. If something *is* reused, move that symbol into `services_v2.py` (or a new shared module) first, in its own preparatory commit, then return here.

- [ ] **Step 3: Delete the v1 surface**

If `services.py` contains only the v1 surface listed in the spec (`MoveRow`, `GameAnalysisData`, `get_game_analysis`, `_load_sf`, `_load_lc0`, `_lc0_move_rows`, `_lc0_summary_kwargs`):

```bash
git rm games/services.py
```

If anything else lives there, delete only the listed symbols (and their helpers) with `Edit`, and leave the file with what remains.

- [ ] **Step 4: Run the full games suite + static gate**

```bash
ruff check games/
pytest games/tests/ -v
mypy games/
```

Expected: all clean. Any ImportError points to a missed import migration — fix and re-run.

- [ ] **Step 5: Commit**

```bash
git add -A games/
git commit -m "$(printf '%s\n' \
  'refactor(#209): delete games.services v1 board surface' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 12: Delete dead-shadowed `games/tests.py`

**Files:**
- Delete: `services/app/games/tests.py`

- [ ] **Step 1: Confirm nothing imports from it**

```bash
grep -rn "from games.tests\b\|from games import tests\b" --include="*.py" .. 2>/dev/null \
  | grep -v __pycache__ | grep -v "games/tests/"
```

Expected: zero hits.

- [ ] **Step 2: Confirm pytest does not discover it under the current layout**

```bash
pytest --collect-only games/tests.py 2>&1 | tail -10
```

Expected: empty collection or an error stating no tests collected (because pytest discovers `games/tests/` package and the standalone `games/tests.py` is shadowed). If it *does* collect tests, stop — re-verify the [[games_tests_shadowed]] assumption before deleting.

- [ ] **Step 3: Delete the file**

```bash
git rm games/tests.py
```

- [ ] **Step 4: Run the full games suite + static gate**

```bash
ruff check games/
pytest games/tests/ -v
```

Expected: all PASS, same test count as before the delete.

- [ ] **Step 5: Commit**

```bash
git commit -m "$(printf '%s\n' \
  'chore(#209): delete dead-shadowed games/tests.py' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

---

## Task 13: Final gate + acceptance-criteria validation

**Files:** none modified.

- [ ] **Step 1: Run the full quality gate from `services/app/`**

```bash
source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate
cd /Users/christopherwebster/Projects/wood_league/.claude/worktrees/issue+209-board-builder-v2/services/app

ruff check .
bandit -ll -r games/ analysis/ -x tests/
xenon --max-absolute B --max-modules B --max-average A games/
mypy games/ analysis/
pytest --cov=games --cov-report=term-missing
```

Expected: every step exits 0. Coverage on `games/board_builder.py` and `games/services_v2.py` ≥ baseline. Note any regressions and address before declaring done.

- [ ] **Step 2: Acceptance-criteria checklist (from spec § Acceptance criteria)**

Run each check and tick the box:

1. **Single board entry point in views.py.**
   ```bash
   grep -n "from games.services\b\|GameAnalysisData\|MoveRow\b" games/views.py
   ```
   Expected: zero hits.

2. **Single `build_board_frames` signature.**
   ```bash
   /Users/christopherwebster/Projects/wood_league/.venv/bin/python -c "
   import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
   import django; django.setup()
   from games.board_builder import build_board_frames
   try:
       build_board_frames('dummy_data_arg_as_positional')
   except TypeError as e:
       print('OK — legacy positional shape rejected:', e); raise SystemExit(0)
   raise SystemExit('FAIL — positional call did not raise TypeError')
   "
   ```
   Expected: `OK — legacy positional shape rejected: …`.

3. **Live LC0 + SF labels.** Manual: start the dev server (see [[project_run_app_locally_worktree]]), open an analysed game's analysis page, confirm both blue and tobacco arrows show labels of the expected forms.

4. **Full gate green** — covered by Step 1.

5. **Integration test catches the bug it was added for.**
   ```bash
   git stash
   git checkout HEAD~N -- games/views.py templates/games/_board_partial.html games/board_builder.py
       # ^^ N = number of commits since main; verify by `git log --oneline main..HEAD`
   pytest games/tests/test_analysis_view_integration.py -v
   git checkout HEAD -- games/views.py templates/games/_board_partial.html games/board_builder.py
   git stash pop 2>/dev/null || true
   ```
   Expected on the legacy code: the LC0-label assertion FAILS. Confirms the test would have caught the original regression. (If your branch is too entangled to cleanly stash-and-revert, mark this as "verified manually during Task 6 Step 2" — that earlier red-test run already proved the same property.)

6. **No vestigial symbols in the tree.**
   ```bash
   git grep -n "GameAnalysisData\b\|MoveRow\b\|arrows_by_ply\|arrow_data_json\|arrowsByPly\|board-arrows-json" \
     -- games/ analysis/ dashboard/ api/ templates/
   ```
   Expected: zero hits. Any remaining hit is unfinished cleanup.

- [ ] **Step 3: Update the project memory**

Append a one-line entry to `/Users/christopherwebster/.claude/projects/-Users-christopherwebster-Projects-wood-league/memory/MEMORY.md` and add a new memory file for #209 documenting the cutover (similar to the existing `project_208_analysis_restyle.md` style). Single fact: "v1 board surface retired; `build_board_frames` is single-signature; `services.py` v1 deleted; integration test in `games/tests/test_analysis_view_integration.py` is the guard against re-regression."

- [ ] **Step 4: Final commit (if anything in Step 2/3 surfaced fixes)**

If Steps 1–3 produced any code changes (test additions, memory update), commit them as a single tidy-up:

```bash
git add -A
git commit -m "$(printf '%s\n' \
  'chore(#209): final-gate tidy + memory update' \
  '' \
  'Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 5: Hand off to finishing-a-development-branch**

The branch is ready for review. Invoke `superpowers:finishing-a-development-branch` to present merge / PR / keep / discard options. Recommend the user choose "Push and create a Pull Request" — this work needs human + CI review before landing.
