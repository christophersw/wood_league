# Issue #188 Phase B — Schema + persistence for SF WDL

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> ## 🟢 2026-05-21 refresh — migration step is NO-OP, skip Task B1
>
> The fresh-start DB reset (PR #192, squash commit `f8d78d1`) folded Phase B's schema additions into the new `0001_initial` per app:
>
> - `MoveAnalysis.wdl_(win|draw|loss)` played-move triple ✅ already in init
> - `MoveAnalysis.wdl_(win|draw|loss)_(1|2|3)` per-candidate triples ✅ already in init
> - `MoveAnalysis.wdl_(win|draw|loss)_adj` derived White-frame triple ✅ already in init (populated by Phase C; null until then)
> - `GameAnalysis.normalize_to_pawn_value` ✅ already in init
>
> Prod and test DBs both carry these columns now. **Skip Task B1 entirely** (model edits + makemigrations + migrate). Tasks B2 (raw passthrough in `derive_sf_game`) and B3 (writes in `complete_stockfish_job`) remain the actual work; both also need updating to match the field names the post-reset model uses — re-skim `services/app/analysis/models.py::MoveAnalysis` and `GameAnalysis` before executing to confirm the names below still match.
>
> **Prerequisite:** Phase A (worker emits SF WDL + NPV via `StockfishCompleteSerializer`) is merged at `e7ff7bc` (PR #190).

**Goal:** Wire `derive_sf_game` to pass Phase A's raw WDL + NPV payload fields through to the (already-present) `MoveAnalysis` / `GameAnalysis` columns. No derivation math changes yet — Phase C does that.

**Architecture (post-refresh):** Schema is in place. Phase B is pure code wiring: `derive_sf_game._derive_one_move` adds raw passthrough of the new fields with no math change. `complete_stockfish_job` extends its `MoveAnalysis(...)` bulk-create + `GameAnalysis` `update_or_create` defaults to write the new columns. The `wdl_*_adj` columns stay null on the Phase B path — Phase C populates them.

**Tech Stack:** Django 5, DRF, PostgreSQL, pytest, pytest-django.

---

## Conventions for all tasks (read first)

- **venv:** `source .venv/bin/activate` before any Python/pytest/bandit/manage.py command.
- **Quality-gate hook:** active — keep functions small, expect transient TDD red.
- **Test placement:** `services/app/analysis/tests/test_<mod>.py` packages. Never `services/app/games/tests.py` (dead).
- **Django migrations:** generate with `python services/app/manage.py makemigrations analysis --name sf_wdl_columns`. Edit only to add a docstring referencing #188 if missing.
- **Bandit:** `bandit -ll <file>` clean after each `.py` edit.
- **Commit prefix:** `feat(#188):` / `test(#188):` / `chore(#188):` + Co-Authored-By trailer.
- **Branch:** `issue/188-sf-wdl-phase-b`, cut from `main` (or rebased onto post-Phase-A `main`).

---

## File Structure

**Modified:**
- `services/app/analysis/derivation/stockfish.py::_derive_one_move` + `derive_sf_game` — raw passthrough of the new fields (no math change).
- `services/app/analysis/services/jobs.py::complete_stockfish_job` — extend `MoveAnalysis(...)` kwargs + `GameAnalysis.update_or_create` defaults.

**Not modified (post-2026-05-21 refresh — schema already in place):**
- ~~`services/app/analysis/models.py`~~ — columns are already declared on `MoveAnalysis`/`GameAnalysis` in the post-reset model.
- ~~`services/app/analysis/migrations/00XX_sf_wdl_columns.py`~~ — folded into `analysis/migrations/0001_initial.py`. No new migration is required.

**Created:**
- `services/app/analysis/tests/test_sf_wdl_persistence.py` — round-trip: payload → derive_sf_game → bulk_create → DB read; asserts every new field is preserved verbatim.

**Not changed:**
- `chart_data.py`, `accuracy.py`, the Lichess sigmoid call sites in derivation — those move in Phase C.

---

## ~~Task B1: Migration + model fields~~  ✅ done by PR #192 (fresh-start reset)

> **Skip this task.** The 2026-05-21 fresh-start reset folded these model fields and migration into `analysis/migrations/0001_initial.py` directly. Confirm by running `python manage.py makemigrations --dry-run` — expected output: `No changes detected`. If you see drift, stop and reconcile before continuing.
>
> The original task body is preserved below for historical reference only.

**Files:**
- Modify: `services/app/analysis/models.py`
- Create: `services/app/analysis/migrations/00XX_sf_wdl_columns.py` (via makemigrations)

- [ ] **Step 1: Add fields to `MoveAnalysis`**

In `services/app/analysis/models.py`, append to the `MoveAnalysis` class (after `pv_san_3`):

```python
    # ── #188 Phase B: SF native WDL ────────────────────────────────────
    # Raw played-move triple, mover frame, milli-units. Nullable end-to-end
    # for older SF builds without UCI_ShowWDL.
    wdl_win = models.IntegerField(null=True, blank=True)
    wdl_draw = models.IntegerField(null=True, blank=True)
    wdl_loss = models.IntegerField(null=True, blank=True)
    # Raw per-candidate triples (top 3 MultiPV); fully nullable per line.
    wdl_win_1 = models.IntegerField(null=True, blank=True)
    wdl_draw_1 = models.IntegerField(null=True, blank=True)
    wdl_loss_1 = models.IntegerField(null=True, blank=True)
    wdl_win_2 = models.IntegerField(null=True, blank=True)
    wdl_draw_2 = models.IntegerField(null=True, blank=True)
    wdl_loss_2 = models.IntegerField(null=True, blank=True)
    wdl_win_3 = models.IntegerField(null=True, blank=True)
    wdl_draw_3 = models.IntegerField(null=True, blank=True)
    wdl_loss_3 = models.IntegerField(null=True, blank=True)
    # Derived: White-frame rescaled WDL triple. SF rescale is identity
    # (frame-mirror only); columns exist for chart symmetry with Lc0. Populated
    # in Phase C; null in Phase B.
    wdl_win_adj = models.IntegerField(null=True, blank=True)
    wdl_draw_adj = models.IntegerField(null=True, blank=True)
    wdl_loss_adj = models.IntegerField(null=True, blank=True)
```

- [ ] **Step 2: Add field to `GameAnalysis`**

```python
    # #188 Phase B: SF NormalizeToPawnValue captured at analyse time, for
    # reproducibility across SF builds. Nullable for older builds.
    normalize_to_pawn_value = models.IntegerField(null=True, blank=True)
```

- [ ] **Step 3: Update class docstrings**

Append to `MoveAnalysis` docstring:
```
    #188 Phase B added raw WDL fields (wdl_(win|draw|loss)(_1|_2|_3)?)
    and derived wdl_*_adj. Phase B persists raw only — Phase C populates
    the _adj columns and switches derivation to feed off wdl_mu.
```

Append to `GameAnalysis` docstring:
```
    #188 Phase B added normalize_to_pawn_value (engine build constant).
```

- [ ] **Step 4: Generate migration**

Run:
```bash
cd services/app && python manage.py makemigrations analysis --name sf_wdl_columns
```
Expected: a single new migration file under `services/app/analysis/migrations/` adding the 16 columns.

- [ ] **Step 5: Apply migration to dev test DB**

Run:
```bash
DJANGO_ENV=test python manage.py migrate analysis
```
Expected: `Applying analysis.00XX_sf_wdl_columns... OK`.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/analysis/models.py
git add services/app/analysis/models.py services/app/analysis/migrations/00XX_sf_wdl_columns.py
git commit -m "$(cat <<'EOF'
feat(#188): MoveAnalysis + GameAnalysis gain SF WDL columns

Mirrors the Lc0MoveAnalysis WDL shape on Stockfish: 12 nullable raw
columns (played + 3 candidates) + 3 nullable wdl_*_adj columns
(populated in Phase C). GameAnalysis gains normalize_to_pawn_value
for SF-build reproducibility.

Phase B persists raw; derivation still cp-based until Phase C.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B2: `derive_sf_game` raw passthrough

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py` (`_derive_one_move`, `derive_sf_game`)
- Modify: existing golden vector fixtures iff they shape-check the derived-moves dict (add nullable WDL keys).

- [ ] **Step 1: Write the failing test**

Create `services/app/analysis/tests/test_sf_wdl_persistence.py`:
```python
"""Tests for #188 Phase B — raw WDL passthrough in derive_sf_game."""
from analysis.derivation.stockfish import derive_sf_game


def _payload(**overrides):
    move = {
        "ply": 1, "san": "e4", "fen": "x" * 30,
        "cp_eval": 30, "mate_in": None,
        "arrow_uci_1": "e7e5", "arrow_uci_2": "c7c5", "arrow_uci_3": "",
        "arrow_score_1": 55.0, "arrow_score_2": 52.0, "arrow_score_3": None,
        "pv_san_1": '["e5"]', "pv_san_2": '["c5"]', "pv_san_3": None,
        "wdl_win": 120, "wdl_draw": 850, "wdl_loss": 30,
        "wdl_win_1": 120, "wdl_draw_1": 850, "wdl_loss_1": 30,
        "wdl_win_2": 110, "wdl_draw_2": 860, "wdl_loss_2": 30,
        "wdl_win_3": None, "wdl_draw_3": None, "wdl_loss_3": None,
    }
    move.update(overrides)
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [move],
    }
    return payload


def test_derive_sf_game_passes_wdl_through_verbatim():
    derived = derive_sf_game(_payload(), game=None)
    m = derived["moves"][0]
    assert (m["wdl_win"], m["wdl_draw"], m["wdl_loss"]) == (120, 850, 30)
    assert (m["wdl_win_1"], m["wdl_draw_1"], m["wdl_loss_1"]) == (120, 850, 30)
    assert m["wdl_loss_3"] is None
    # Phase B: _adj columns stay null until Phase C.
    assert m["wdl_win_adj"] is None
    assert m["wdl_draw_adj"] is None
    assert m["wdl_loss_adj"] is None


def test_derive_sf_game_passes_npv_through():
    derived = derive_sf_game(_payload(), game=None)
    assert derived["normalize_to_pawn_value"] == 328


def test_derive_sf_game_handles_missing_wdl_fields():
    """Backwards compat: a payload without WDL fields still derives."""
    payload = _payload()
    move = payload["moves"][0]
    for k in list(move):
        if k.startswith("wdl_"):
            del move[k]
    del payload["normalize_to_pawn_value"]
    derived = derive_sf_game(payload, game=None)
    m = derived["moves"][0]
    assert m["wdl_win"] is None and m["wdl_draw"] is None and m["wdl_loss"] is None
    assert m["wdl_win_1"] is None
    assert derived["normalize_to_pawn_value"] is None
```

Run: `cd services/app && pytest analysis/tests/test_sf_wdl_persistence.py -v`
Expected: FAIL — keys not in derived output.

- [ ] **Step 2: Extend `_derive_one_move` return dict**

In `services/app/analysis/derivation/stockfish.py::_derive_one_move`, locate the `return { ... }` block. Add (after `pv_san_3`):

```python
        # #188 Phase B: raw WDL passthrough. Phase C populates _adj from these.
        "wdl_win": move.get("wdl_win"),
        "wdl_draw": move.get("wdl_draw"),
        "wdl_loss": move.get("wdl_loss"),
        "wdl_win_1": move.get("wdl_win_1"),
        "wdl_draw_1": move.get("wdl_draw_1"),
        "wdl_loss_1": move.get("wdl_loss_1"),
        "wdl_win_2": move.get("wdl_win_2"),
        "wdl_draw_2": move.get("wdl_draw_2"),
        "wdl_loss_2": move.get("wdl_loss_2"),
        "wdl_win_3": move.get("wdl_win_3"),
        "wdl_draw_3": move.get("wdl_draw_3"),
        "wdl_loss_3": move.get("wdl_loss_3"),
        # Phase B leaves _adj null; Phase C populates as frame-mirror identity.
        "wdl_win_adj": None,
        "wdl_draw_adj": None,
        "wdl_loss_adj": None,
```

- [ ] **Step 3: Extend `derive_sf_game` return**

At the bottom of `derive_sf_game`, change:

```python
    return {
        "engine_depth": int(raw_payload["engine_depth"]),
        "summary_cp": before_white,
        **aggregates,
        "moves": derived_moves,
    }
```

to:

```python
    return {
        "engine_depth": int(raw_payload["engine_depth"]),
        "summary_cp": before_white,
        # #188 Phase B: pass NPV through for persistence; nullable.
        "normalize_to_pawn_value": raw_payload.get("normalize_to_pawn_value"),
        **aggregates,
        "moves": derived_moves,
    }
```

- [ ] **Step 4: Update the module docstring Changelog**

Append:
```
    2026-05-21 (#188/B): raw SF WDL triples + NPV pass through derive_sf_game
        unchanged. Phase C will switch the accuracy/classification math to
        feed off wdl_mu derived from these triples.
```

- [ ] **Step 5: Run tests**

Run: `cd services/app && pytest analysis/tests/test_sf_wdl_persistence.py -v`
Expected: 3 tests PASS.

Run: `cd services/app && pytest analysis/derivation/tests/ -v`
Expected: pre-existing golden-vector tests still PASS — the new dict keys are nullable and don't affect any existing assertion.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/analysis/derivation/stockfish.py
git add services/app/analysis/derivation/stockfish.py services/app/analysis/tests/test_sf_wdl_persistence.py
git commit -m "$(cat <<'EOF'
feat(#188): derive_sf_game passes raw WDL + NPV through unchanged

Phase B passthrough only: _derive_one_move emits the 12 WDL keys + 3
null wdl_*_adj placeholders, derive_sf_game surfaces NPV at the top
level. Accuracy/classification math stays cp-based until Phase C.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B3: Persist WDL + NPV in `complete_stockfish_job`

**Files:**
- Modify: `services/app/analysis/services/jobs.py::complete_stockfish_job`

- [ ] **Step 1: Write the failing test**

Append to `services/app/analysis/tests/test_sf_wdl_persistence.py`:
```python
import pytest
from django.utils import timezone

from analysis.models import AnalysisJob, GameAnalysis, MoveAnalysis
from analysis.services.jobs import complete_stockfish_job
from games.models import Game  # adjust import path if Game lives elsewhere


@pytest.mark.django_db
def test_complete_stockfish_job_persists_wdl_and_npv():
    game = Game.objects.create(...)  # use existing fixture/factory if available
    job = AnalysisJob.objects.create(
        game=game, status=AnalysisJob.STATUS_RUNNING,
        worker_id="w-1", engine="stockfish", depth=20,
    )
    payload = _payload()  # from earlier in this file
    payload["worker_id"] = "w-1"

    complete_stockfish_job(
        job_id=job.id, worker_id="w-1", key_prefix=None, payload=payload,
    )

    ga = GameAnalysis.objects.get(game=game)
    assert ga.normalize_to_pawn_value == 328

    move = MoveAnalysis.objects.get(analysis=ga, ply=1)
    assert (move.wdl_win, move.wdl_draw, move.wdl_loss) == (120, 850, 30)
    assert (move.wdl_win_1, move.wdl_draw_1, move.wdl_loss_1) == (120, 850, 30)
    assert move.wdl_loss_3 is None
    # _adj columns stay null in Phase B.
    assert move.wdl_win_adj is None
```

> **Game fixture note:** the existing `analysis/tests/` directory will have either a `conftest.py` factory or an existing creation pattern. Reuse it instead of hand-rolling `Game.objects.create(...)`.

Run: `cd services/app && pytest analysis/tests/test_sf_wdl_persistence.py::test_complete_stockfish_job_persists_wdl_and_npv -v`
Expected: FAIL — `MoveAnalysis(...)` doesn't accept `wdl_win=...` yet (kwargs unknown).

- [ ] **Step 2: Extend `MoveAnalysis(...)` bulk_create kwargs**

In `services/app/analysis/services/jobs.py::complete_stockfish_job`, locate the `MoveAnalysis(...)` constructor call inside `MoveAnalysis.objects.bulk_create([...])`. Append (after `pv_san_3=m["pv_san_3"]`):

```python
                # #188 Phase B: raw SF WDL triples + null _adj placeholders.
                wdl_win=m["wdl_win"],
                wdl_draw=m["wdl_draw"],
                wdl_loss=m["wdl_loss"],
                wdl_win_1=m["wdl_win_1"],
                wdl_draw_1=m["wdl_draw_1"],
                wdl_loss_1=m["wdl_loss_1"],
                wdl_win_2=m["wdl_win_2"],
                wdl_draw_2=m["wdl_draw_2"],
                wdl_loss_2=m["wdl_loss_2"],
                wdl_win_3=m["wdl_win_3"],
                wdl_draw_3=m["wdl_draw_3"],
                wdl_loss_3=m["wdl_loss_3"],
                wdl_win_adj=m["wdl_win_adj"],
                wdl_draw_adj=m["wdl_draw_adj"],
                wdl_loss_adj=m["wdl_loss_adj"],
```

- [ ] **Step 3: Extend `GameAnalysis.update_or_create` defaults**

In the same function, locate the `defaults=dict(...)` block. Append:

```python
                # #188 Phase B: SF build constant for reproducibility.
                normalize_to_pawn_value=derived.get("normalize_to_pawn_value"),
```

- [ ] **Step 4: Run tests**

Run: `cd services/app && pytest analysis/tests/test_sf_wdl_persistence.py -v`
Expected: 4 tests PASS.

Run the full SF persistence suite to confirm no regression:
`cd services/app && pytest analysis/tests/ api/tests/ -v -k stockfish`

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/app/analysis/services/jobs.py
git add services/app/analysis/services/jobs.py services/app/analysis/tests/test_sf_wdl_persistence.py
git commit -m "$(cat <<'EOF'
feat(#188): complete_stockfish_job persists SF WDL + NPV

Bulk-create MoveAnalysis rows now carry the 12 raw WDL columns + 3
null _adj placeholders; update_or_create on GameAnalysis carries
normalize_to_pawn_value. Phase B is purely persistence — Phase C
populates _adj and switches derivation to wdl_mu.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B4: PR

**Files:** N/A

- [ ] **Step 1: Push + create PR**

```bash
git push -u origin issue/188-sf-wdl-phase-b
gh pr create --title "feat(#188): persist SF WDL + NormalizeToPawnValue (Phase B)" --body "$(cat <<'EOF'
## Summary
- New migration adds 12 nullable WDL columns + 3 nullable wdl_*_adj placeholders to ``MoveAnalysis`` and ``normalize_to_pawn_value`` to ``GameAnalysis``.
- ``derive_sf_game`` passes the raw WDL fields + NPV through unchanged. No math change — accuracy / classification / chart all stay cp-based until Phase C.
- ``complete_stockfish_job`` writes the new columns on every Stockfish completion.

Builds on Phase A (worker emits the fields). Phase C will populate ``wdl_*_adj`` (identity transform, frame-mirror only) and switch ``_derive_one_move`` to feed accuracy off ``wdl_mu``.

## Test plan
- [ ] ``test_sf_wdl_persistence.py`` — passthrough + persistence round-trip
- [ ] Pre-existing SF golden-vector tests still pass (nullable additions only)
- [ ] Pre-existing SF API tests still pass (serializer + view shape unchanged from Phase A)
- [ ] Manually verify the migration applies cleanly on the dev test DB

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

- [ ] Migration touches only the analysis app (no incidental cross-app changes)
- [ ] All 15 `MoveAnalysis` columns nullable; 1 `GameAnalysis` column nullable
- [ ] No new derivation math (Phase C scope) — `_derive_one_move` only adds passthrough
- [ ] `wdl_*_adj` columns are populated as `None` in Phase B (Phase C populates them)
- [ ] Bulk_create kwargs match the derived dict keys 1:1
- [ ] Pre-existing SF tests still green
- [ ] No reference to `wdl_mu` / `accuracy.win_pct` deletions in this PR's diff (Phase C/D scope)

---

## Out of scope (do not touch in Phase B)

- `_derive_one_move`'s accuracy/classification math (Phase C).
- `chart_data.winpct_payload` (Phase D).
- `_extract_arrows_and_pvs`'s sigmoid conversion (Phase D).
- Backfill of historical analyses (re-analyze policy).
