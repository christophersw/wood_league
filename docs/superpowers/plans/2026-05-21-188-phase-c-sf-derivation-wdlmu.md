# Issue #188 Phase C — SF derivation switches to WDL_mu

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> ## 🟢 2026-05-21 refresh
>
> The 2026-05-21 fresh-start DB reset (PR #192, commit `f8d78d1`) folded Phase B's schema additions into `0001_initial`. The columns this plan references (`wdl_*`, `wdl_*_(1|2|3)`, `wdl_*_adj`, `normalize_to_pawn_value`) are already present in prod and test DBs.
>
> Phase C's work is unchanged in shape — the same derivation rewrite, the same `_adj` populator, the same golden vectors. Task C5 (persistence check) now confirms columns that the schema has carried since the reset, not columns Phase B added.
>
> **Prerequisites:** Phase A is merged at `e7ff7bc` (PR #190). Phase B's code wiring (Task B2 + B3 — passthrough + bulk_create writes) must land first. The Phase B PR is purely code; no migration.

**Plan refinement note (still applies):** Re-read the merged Phase A + Phase B diffs and reconcile any drift in derived-dict keys, model field names, and golden-vector fixture shape before executing. The code snippets here assume the field names declared in earlier plans.

**Goal:** Switch `_derive_one_move` to drive Win% / accuracy / classification-gap math off the SF-native WDL triple (`wdl_mu`) instead of the Lichess `win_pct(cp)` sigmoid. CPL ladder stays cp-based (still the right tool for severity bands). Populate `wdl_*_adj` as the White-frame mirror of `wdl_*` (identity transform — SF needs no population rescale, unlike LC0). Keep `accuracy.win_pct` only as a guarded fallback for missing-WDL builds.

**Architecture:** `derivation/stockfish.py` gains a `_sf_wdl` helper module (or inlined functions) that (1) rotates a mover-frame WDL triple to White's frame, (2) computes `wdl_mu = (win + draw/2) / 1000` in either frame, (3) computes the classifier's `second_best_gap` as a raw WDL_mu gap (no inverse sigmoid). `_derive_one_move` walks the game with WDL_mu, feeding `move_accuracy` / `game_accuracy` (which already accept Win% on [0, 100]) by multiplying mu by 100. The cp-derived `cpl` is unchanged. Per-side accuracy numbers for *every* existing analysis change — that is the explicit acceptance criterion of #188.

**Tech Stack:** Python 3, Django, pytest. No new deps.

---

## Conventions for all tasks (read first)

- **venv:** `source .venv/bin/activate` before any Python/pytest/bandit/manage.py command.
- **Quality-gate hook:** active. Keep functions small. Expect transient TDD red.
- **Test placement:** `services/app/analysis/derivation/tests/test_<mod>.py` and `services/app/analysis/tests/`. Never `services/app/games/tests.py`.
- **Bandit:** `bandit -ll <file>` clean after every `.py` edit.
- **Commit prefix:** `feat(#188):` / `test(#188):` / `chore(#188):` / `refactor(#188):` + Co-Authored-By trailer.
- **Branch:** `issue/188-sf-wdl-phase-c`, cut from post-Phase-B `main`.
- **Golden vectors:** the existing fixtures under `services/app/analysis/derivation/golden_vectors/` pin accuracy/classification outputs for sample games. Every per-side accuracy number for every fixture changes in Phase C. We add new WDL-bearing fixtures alongside the old cp-only fixtures; the old fixtures continue to exercise the missing-WDL fallback path.

---

## File Structure

**Modified:**
- `services/app/analysis/derivation/stockfish.py` — replace `_derive_one_move`, replace `_gap_from_arrow_scores`, delete `_cp_from_win_pct` + `_WIN_PCT_K`, update `_build_game_aggregates` to build `all_win_pcts` from WDL.
- `services/app/analysis/derivation/_calibration.py` — add `sf_wdl_mu_white(...)` helper (frame-mirror + mu), only if a similar Lc0 helper exists that we can extend; otherwise inline in `stockfish.py`.
- `services/app/analysis/derivation/golden_vectors/*.json` — annotate or duplicate as needed; the old fixtures keep the missing-WDL fallback signature.

**Created:**
- `services/app/analysis/derivation/tests/test_stockfish_wdl_mu.py` — unit tests for the new WDL_mu paths: frame mirror, mu computation, mu gap → classification, missing-WDL fallback, mate saturation, black-mover correctness, 1-ply game.
- `services/app/analysis/derivation/golden_vectors/sf_wdl_<game_name>.json` — at least 2 new fixtures generated from real Phase-A worker runs (a quiet positional game and a tactical one), with pinned post-Phase-C derived output.

**Not changed:**
- `chart_data.py` (Phase D).
- `_extract_arrows_and_pvs` worker side (Phase D).
- `accuracy.win_pct` (kept; only sigmoid call site left after Phase C is the fallback).

---

## Task C1: WDL helpers (frame mirror + mu + gap)

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py`

- [ ] **Step 1: Write the failing tests**

Create `services/app/analysis/derivation/tests/test_stockfish_wdl_mu.py`:
```python
"""Tests for #188 Phase C — SF WDL_mu math."""
import pytest

from analysis.derivation.stockfish import (
    _sf_wdl_mu_white,
    _sf_wdl_mover_to_white,
    _gap_from_arrow_wdl_mu,
)


@pytest.mark.parametrize("triple,expected", [
    ((1000, 0, 0), 1.0),
    ((0, 1000, 0), 0.5),
    ((0, 0, 1000), 0.0),
    ((100, 800, 100), 0.5),
    ((200, 700, 100), 0.55),
])
def test_sf_wdl_mu_white(triple, expected):
    assert _sf_wdl_mu_white(*triple) == pytest.approx(expected, abs=1e-9)


def test_sf_wdl_mover_to_white_white_mover_identity():
    assert _sf_wdl_mover_to_white(120, 850, 30, mover_is_white=True) == (120, 850, 30)


def test_sf_wdl_mover_to_white_black_mover_swaps_win_loss():
    assert _sf_wdl_mover_to_white(120, 850, 30, mover_is_white=False) == (30, 850, 120)


def test_gap_from_arrow_wdl_mu_simple():
    # mu_1 = 0.6, mu_2 = 0.5 → mu_gap = 0.1
    assert _gap_from_arrow_wdl_mu(
        mu_1=0.6, mu_2=0.5, normalize_to_pawn_value=328,
    ) == pytest.approx(0.1 * 328 * 2)


def test_gap_from_arrow_wdl_mu_none_for_missing():
    assert _gap_from_arrow_wdl_mu(mu_1=None, mu_2=0.5, normalize_to_pawn_value=328) is None
    assert _gap_from_arrow_wdl_mu(mu_1=0.5, mu_2=None, normalize_to_pawn_value=328) is None


def test_gap_from_arrow_wdl_mu_falls_back_to_default_npv():
    """When NPV is missing, use SF 16 default of 328."""
    assert _gap_from_arrow_wdl_mu(
        mu_1=0.6, mu_2=0.5, normalize_to_pawn_value=None,
    ) == pytest.approx(0.1 * 328 * 2)


def test_gap_from_arrow_wdl_mu_clamps_non_negative():
    # Caller-side bug protection: mu_2 > mu_1 should still return non-negative.
    assert _gap_from_arrow_wdl_mu(
        mu_1=0.4, mu_2=0.6, normalize_to_pawn_value=328,
    ) == 0.0
```

Run: `cd services/app && pytest analysis/derivation/tests/test_stockfish_wdl_mu.py -v`
Expected: FAIL — helpers not yet exported.

- [ ] **Step 2: Implement helpers**

In `services/app/analysis/derivation/stockfish.py`, near the top (after imports, before existing helpers), add:

```python
# #188 Phase C: SF native WDL math. Mover/White frame handling + scalar mu.
# Frame note: SF emits WDL in the side-to-move frame. To put it in White's
# frame for a Black move, swap wins↔losses (draws are symmetric).
# NPV note: NormalizeToPawnValue is SF's published scaling constant (default
# 328 for SF 16+); a mu gap of Δ translates to ~2·Δ·NPV cp around mu=0.5.

_SF_DEFAULT_NPV = 328  # SF 16+ default; used when payload NPV is None.


def _sf_wdl_mover_to_white(
    win: int, draw: int, loss: int, *, mover_is_white: bool,
) -> tuple[int, int, int]:
    """Rotate a mover-frame WDL triple to White's frame.

    Args:
        win: Mover-frame W in milli-units.
        draw: Mover-frame D in milli-units.
        loss: Mover-frame L in milli-units.
        mover_is_white: True iff the mover at the searched position is White.

    Returns:
        (W_white, D_white, L_white) in milli-units.
    """
    if mover_is_white:
        return (win, draw, loss)
    return (loss, draw, win)


def _sf_wdl_mu_white(win: int, draw: int, loss: int) -> float:
    """Expected-score fraction in [0, 1] from a White-frame WDL triple.

    Args:
        win: White-frame W in milli-units.
        draw: White-frame D in milli-units.
        loss: White-frame L in milli-units (unused; kept for symmetric signature).

    Returns:
        ``(W + D/2) / 1000``, where the denominator is the spec sum-of-milli.
    """
    return (win + draw / 2.0) / 1000.0


def _gap_from_arrow_wdl_mu(
    *,
    mu_1: float | None,
    mu_2: float | None,
    normalize_to_pawn_value: int | None,
) -> float | None:
    """Cp-equivalent gap between top-2 candidates from mover-frame WDL_mu.

    Replacement for ``_gap_from_arrow_scores`` (which detoured through the
    inverse Lichess sigmoid). SF's published scaling around mu=0.5 is
    ``cp ≈ (mu - 0.5) · NPV · 2``, so a mu gap of Δ → cp gap of ``Δ · NPV · 2``.

    Args:
        mu_1: Mover-frame WDL_mu for the top candidate.
        mu_2: Mover-frame WDL_mu for the second candidate.
        normalize_to_pawn_value: SF build constant; ``None`` falls back to 328.

    Returns:
        Non-negative cp gap, or None when either mu is missing.
    """
    if mu_1 is None or mu_2 is None:
        return None
    npv = normalize_to_pawn_value if normalize_to_pawn_value is not None else _SF_DEFAULT_NPV
    return max(0.0, (mu_1 - mu_2) * npv * 2.0)
```

- [ ] **Step 3: Run + commit**

Run: `cd services/app && pytest analysis/derivation/tests/test_stockfish_wdl_mu.py -v`
Expected: 8 tests PASS.

```bash
bandit -ll services/app/analysis/derivation/stockfish.py
git add services/app/analysis/derivation/stockfish.py services/app/analysis/derivation/tests/test_stockfish_wdl_mu.py
git commit -m "$(cat <<'EOF'
feat(#188): SF WDL_mu helpers (frame mirror + mu + cp gap)

Adds _sf_wdl_mover_to_white, _sf_wdl_mu_white, _gap_from_arrow_wdl_mu.
SF rescale is identity — only frame mirror, no population rescale (unlike
Lc0). Cp gap uses SF's NormalizeToPawnValue scaling rule. Helpers wired
into _derive_one_move in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C2: Rewrite `_derive_one_move` to use WDL_mu

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py::_derive_one_move`

- [ ] **Step 1: Write the failing tests**

Append to `test_stockfish_wdl_mu.py`:
```python
from analysis.derivation.stockfish import _derive_one_move


def _move(**overrides):
    base = {
        "ply": 1, "san": "e4", "fen": "x" * 30,
        "cp_eval": 30, "mate_in": None,
        "arrow_uci_1": "e7e5", "arrow_uci_2": "c7c5", "arrow_uci_3": "",
        "arrow_score_1": 55.0, "arrow_score_2": 52.0, "arrow_score_3": None,
        "pv_san_1": '["e5"]', "pv_san_2": '["c5"]', "pv_san_3": None,
        "wdl_win": 200, "wdl_draw": 700, "wdl_loss": 100,
        "wdl_win_1": 220, "wdl_draw_1": 700, "wdl_loss_1": 80,
        "wdl_win_2": 180, "wdl_draw_2": 720, "wdl_loss_2": 100,
        "wdl_win_3": None, "wdl_draw_3": None, "wdl_loss_3": None,
    }
    base.update(overrides)
    return base


def test_derive_one_move_uses_wdl_mu_when_present(monkeypatch):
    """Mover-frame mu drives Win% feeding accuracy + classification."""
    out = _derive_one_move(_move(), before_white_mu=0.5, normalize_to_pawn_value=328)
    # Ply 1 = White; mover_is_white=True; mu_after_white = (200 + 350) / 1000 = 0.55
    assert out["wdl_win_adj"] == 200
    assert out["wdl_draw_adj"] == 700
    assert out["wdl_loss_adj"] == 100
    assert out["wdl_mu"] == pytest.approx(0.55)
    # move_win_delta in mover frame: 50 → 55 → drop = -5 (mover gained 5%)
    assert out["move_win_delta"] == pytest.approx(50.0 - 55.0)


def test_derive_one_move_black_mover_swaps_frame():
    move = _move(ply=2, wdl_win=100, wdl_draw=700, wdl_loss=200)
    out = _derive_one_move(move, before_white_mu=0.5, normalize_to_pawn_value=328)
    # Black mover; mover-frame (100, 700, 200) → white-frame (200, 700, 100)
    assert (out["wdl_win_adj"], out["wdl_draw_adj"], out["wdl_loss_adj"]) == (200, 700, 100)
    # mu_white = 0.55
    assert out["wdl_mu"] == pytest.approx(0.55)


def test_derive_one_move_falls_back_to_sigmoid_when_wdl_missing():
    move = _move()
    for k in ("wdl_win", "wdl_draw", "wdl_loss"):
        move[k] = None
    out = _derive_one_move(move, before_white_mu=0.5, normalize_to_pawn_value=328)
    # Fallback path: _adj stays null, wdl_mu derived from win_pct(cp) instead.
    assert out["wdl_win_adj"] is None
    # Should still produce a classification + cpl using cp-based math.
    assert out["classification"] is not None
    assert out["cpl"] is not None


def test_derive_one_move_mate_saturates():
    move = _move(cp_eval=0, mate_in=3, wdl_win=999, wdl_draw=1, wdl_loss=0)
    out = _derive_one_move(move, before_white_mu=0.5, normalize_to_pawn_value=328)
    assert out["wdl_mu"] > 0.99
```

Run: `cd services/app && pytest analysis/derivation/tests/test_stockfish_wdl_mu.py -k derive_one_move -v`
Expected: FAIL — `_derive_one_move` doesn't accept the new kwargs.

- [ ] **Step 2: Rewrite `_derive_one_move`**

Replace the existing `_derive_one_move` function with:

```python
def _derive_one_move(
    move: dict,
    *,
    before_white: int = 0,                 # legacy cp walk; retained for fallback
    before_white_mu: float = 0.5,           # #188: White-frame mu of position before
    normalize_to_pawn_value: int | None = None,
) -> dict:
    """Compute every derived field for one raw Stockfish move entry (#188 Phase C).

    Two paths:
      * WDL path (preferred): the move's mover-frame WDL triple is non-null →
        derive mu in White's frame, populate ``wdl_*_adj`` as the frame-mirror
        identity, feed mu*100 into the Lichess accuracy curve.
      * Sigmoid fallback: WDL absent → ``win_pct(cp)`` drives accuracy, ``_adj``
        stays null. Logged at WARN (caller dedupes per game).

    Args:
        move: One element of ``raw_payload["moves"]`` (Phase B raw contract).
        before_white: White-frame cp eval of the position before the move
            (used only on the fallback path).
        before_white_mu: White-frame WDL_mu of the position before the move
            (used on the WDL path).
        normalize_to_pawn_value: SF build constant for cp-gap derivation.

    Returns:
        Dict carrying raw fields verbatim plus all derived fields. Phase B's
        ``wdl_*_adj`` columns are populated here on the WDL path.
    """
    ply = int(move["ply"])
    mover_is_white = is_white_ply(ply)
    cp_after_white = _saturated_cp(move.get("cp_eval"), move.get("mate_in"))

    # CPL is cp-based on both paths.
    cpl_mover = cpl(
        before_white=before_white, after_white=cp_after_white,
        mover_is_white=mover_is_white,
    )

    wdl_win_mover = move.get("wdl_win")
    wdl_draw_mover = move.get("wdl_draw")
    wdl_loss_mover = move.get("wdl_loss")
    have_wdl = (
        wdl_win_mover is not None
        and wdl_draw_mover is not None
        and wdl_loss_mover is not None
    )

    if have_wdl:
        wdl_win_w, wdl_draw_w, wdl_loss_w = _sf_wdl_mover_to_white(
            wdl_win_mover, wdl_draw_mover, wdl_loss_mover,
            mover_is_white=mover_is_white,
        )
        mu_after_white = _sf_wdl_mu_white(wdl_win_w, wdl_draw_w, wdl_loss_w)
        win_pct_before_mover = (
            before_white_mu if mover_is_white else (1.0 - before_white_mu)
        ) * 100.0
        win_pct_after_mover = (
            mu_after_white if mover_is_white else (1.0 - mu_after_white)
        ) * 100.0
        wdl_win_adj, wdl_draw_adj, wdl_loss_adj = wdl_win_w, wdl_draw_w, wdl_loss_w
        wdl_mu_white = mu_after_white
        # Classifier gap uses raw mu (no inverse sigmoid).
        mu_1 = move.get("wdl_win_1")
        mu_2 = move.get("wdl_win_2")
        if mu_1 is not None:
            mu_1 = _sf_wdl_mu_white(
                move["wdl_win_1"], move["wdl_draw_1"], move["wdl_loss_1"],
            )
            if not mover_is_white:
                mu_1 = 1.0 - mu_1
        if mu_2 is not None:
            mu_2 = _sf_wdl_mu_white(
                move["wdl_win_2"], move["wdl_draw_2"], move["wdl_loss_2"],
            )
            if not mover_is_white:
                mu_2 = 1.0 - mu_2
        gap = _gap_from_arrow_wdl_mu(
            mu_1=mu_1, mu_2=mu_2,
            normalize_to_pawn_value=normalize_to_pawn_value,
        )
    else:
        # Fallback: sigmoid path. _adj stays null.
        mover_cp_before = before_white if mover_is_white else -before_white
        mover_cp_after = cp_after_white if mover_is_white else -cp_after_white
        win_pct_before_mover = win_pct(mover_cp_before)
        win_pct_after_mover = win_pct(mover_cp_after)
        wdl_win_adj = wdl_draw_adj = wdl_loss_adj = None
        wdl_mu_white = None
        gap = _gap_from_arrow_scores(
            move.get("arrow_score_1"), move.get("arrow_score_2"),
        )

    move_win_delta_mover = win_pct_before_mover - win_pct_after_mover
    move_acc = move_accuracy(win_pct_before_mover, win_pct_after_mover)

    classification = classify_sf_move(
        cpl_mover=cpl_mover,
        second_best_gap=gap,
        mover_win_pct=win_pct_before_mover,
        is_capture_or_sacrifice=False,
    )

    win_pct_after_white = (
        wdl_mu_white * 100.0 if wdl_mu_white is not None else win_pct(cp_after_white)
    )

    return {
        # Raw passthrough.
        "ply": ply,
        "san": move["san"],
        "fen": move["fen"],
        "cp_eval": int(move["cp_eval"]) if move.get("cp_eval") is not None else 0,
        "mate_in": move.get("mate_in"),
        "arrow_uci_1": move.get("arrow_uci_1") or "",
        "arrow_uci_2": move.get("arrow_uci_2"),
        "arrow_uci_3": move.get("arrow_uci_3"),
        "arrow_score_1": move.get("arrow_score_1"),
        "arrow_score_2": move.get("arrow_score_2"),
        "arrow_score_3": move.get("arrow_score_3"),
        "pv_san_1": move.get("pv_san_1"),
        "pv_san_2": move.get("pv_san_2"),
        "pv_san_3": move.get("pv_san_3"),
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
        # Derived.
        "cpl": cpl_mover,
        "move_win_delta": move_win_delta_mover,
        "classification": classification,
        "best_move": move.get("arrow_uci_1") or "",
        "wdl_win_adj": wdl_win_adj,
        "wdl_draw_adj": wdl_draw_adj,
        "wdl_loss_adj": wdl_loss_adj,
        "wdl_mu": wdl_mu_white,
        # Walking state (stripped by ``derive_sf_game``).
        "_cp_after_white": cp_after_white,
        "_mu_after_white": wdl_mu_white if wdl_mu_white is not None else win_pct(cp_after_white) / 100.0,
        "_move_acc": move_acc,
        "_win_pct_after_white": win_pct_after_white,
        "_used_wdl": have_wdl,
    }
```

> **`wdl_mu` column note:** Phase B added `wdl_*_adj` but not `wdl_mu`. We rely on `wdl_*_adj` carrying the White-frame triple; consumers can recompute `mu = (W_adj + D_adj/2) / 1000` on read. If a follow-up wants `wdl_mu` as a stored column, add it to a new migration; this plan deliberately keeps the schema slim.

Update the function docstring `Limitations` block to drop the "sigmoid-derived gap" caveat and add: "WDL path: classifier gap is the raw mu-gap × NPV × 2; sigmoid fallback only fires when the engine did not emit WDL."

- [ ] **Step 3: Run tests**

Run: `cd services/app && pytest analysis/derivation/tests/test_stockfish_wdl_mu.py -v`
Expected: all PASS (rewrite + helper tests).

- [ ] **Step 4: Commit**

```bash
bandit -ll services/app/analysis/derivation/stockfish.py
git add services/app/analysis/derivation/stockfish.py services/app/analysis/derivation/tests/test_stockfish_wdl_mu.py
git commit -m "$(cat <<'EOF'
feat(#188): _derive_one_move uses SF WDL_mu when present

WDL path: mover-frame triple → White-frame mu → feeds Lichess accuracy
curve via mu*100. _adj columns populated (identity transform — SF needs
no population rescale). Classifier gap uses raw mu-gap × NPV × 2.

Sigmoid fallback retained verbatim for missing-WDL builds (older SF, or
pathological positions); _adj + wdl_mu stay null on that path.

Per-side accuracy numbers will change for every newly derived game.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C3: Update `derive_sf_game` walk + aggregates

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py::derive_sf_game`, `_build_game_aggregates`

- [ ] **Step 1: Update the walk to thread `before_white_mu`**

In `derive_sf_game`, replace the walk loop:

```python
def derive_sf_game(raw_payload: dict, game: Any) -> dict:  # noqa: ARG001
    """Derive every Stockfish-analysis field from a validated raw payload (#188 Phase C).

    The walk threads two "before" channels:
      * ``before_white`` (cp) for the cp-based CPL ladder and the sigmoid
        fallback when WDL is missing.
      * ``before_white_mu`` (WDL_mu in White's frame) for the WDL path.

    Args:
        raw_payload: Dict matching the #161 + #188 raw Stockfish contract.
        game: ``games.Game`` instance; reserved for future Elo-aware
            adjustments (ignored in Phase C).

    Returns:
        Dict shaped for ``GameAnalysis`` model creation, with a nested
        ``moves`` list shaped for ``MoveAnalysis``.
    """
    derived_moves: list[dict] = []
    before_white = 0
    before_white_mu = 0.5  # mu of the starting position (matches cp=0 assumption)
    npv = raw_payload.get("normalize_to_pawn_value")
    all_win_pcts_white: list[float] = [50.0]  # starting position Win% in White's frame
    for move in raw_payload["moves"]:
        result = _derive_one_move(
            move,
            before_white=before_white,
            before_white_mu=before_white_mu,
            normalize_to_pawn_value=npv,
        )
        before_white = result.pop("_cp_after_white")
        before_white_mu = result.pop("_mu_after_white")
        move_acc = result.pop("_move_acc")
        win_pct_after_white = result.pop("_win_pct_after_white")
        result.pop("_used_wdl", None)
        all_win_pcts_white.append(win_pct_after_white)
        result["_move_acc"] = move_acc
        derived_moves.append(result)
    aggregates = _build_game_aggregates(derived_moves, all_win_pcts_white)
    for move in derived_moves:
        move.pop("_move_acc", None)
    return {
        "engine_depth": int(raw_payload["engine_depth"]),
        "summary_cp": before_white,
        "normalize_to_pawn_value": npv,
        **aggregates,
        "moves": derived_moves,
    }
```

> Note: `_build_game_aggregates` itself does not change — it consumes `all_win_pcts_white` (already on the [0, 100] scale, mixed WDL-derived and sigmoid-derived) and per-side mover indices. The Lichess accuracy curve runs identically on both sources of Win%.

- [ ] **Step 2: Write the integration test**

Append to `test_stockfish_wdl_mu.py`:
```python
from analysis.derivation.stockfish import derive_sf_game


def test_derive_sf_game_walks_mu_through():
    """Mu walks correctly; ply 2 sees ply 1's mu in its `before_white_mu`."""
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [
            _move(ply=1, wdl_win=200, wdl_draw=700, wdl_loss=100),  # mu_w = 0.55
            _move(ply=2, wdl_win=300, wdl_draw=600, wdl_loss=100),  # Black mover
        ],
    }
    derived = derive_sf_game(payload, game=None)
    assert derived["moves"][0]["wdl_mu"] == pytest.approx(0.55)
    # Ply 2: Black mover, mover (100, 600, 300) → white (300, 600, 100), mu_w = 0.6
    assert derived["moves"][1]["wdl_mu"] == pytest.approx(0.6)


def test_derive_sf_game_top_level_npv_passed_through():
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [_move()],
    }
    assert derive_sf_game(payload, game=None)["normalize_to_pawn_value"] == 328
```

- [ ] **Step 3: Run + commit**

Run: `cd services/app && pytest analysis/derivation/tests/test_stockfish_wdl_mu.py -v`
Expected: all PASS.

Run existing fallback-path coverage (the pre-Phase-A fixtures emit no WDL):
`cd services/app && pytest analysis/derivation/tests/ -v -k sf`
Expected: existing golden vectors PASS via the fallback path (which still reproduces the historical accuracy numbers verbatim).

```bash
bandit -ll services/app/analysis/derivation/stockfish.py
git add services/app/analysis/derivation/stockfish.py services/app/analysis/derivation/tests/test_stockfish_wdl_mu.py
git commit -m "$(cat <<'EOF'
feat(#188): derive_sf_game walks WDL_mu + threads NPV

The walk now carries two "before" channels: cp (legacy fallback) and
White-frame mu (WDL path). NPV is read once and threaded into every
_derive_one_move call. Existing golden vectors (pre-Phase-A, no WDL)
still pass via the sigmoid fallback path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C4: Delete the now-unused inverse sigmoid helpers

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py`

- [ ] **Step 1: Confirm `_cp_from_win_pct` is unused on the WDL path**

Run: `cd services/app && grep -n "_cp_from_win_pct\|_gap_from_arrow_scores\b" analysis/derivation/stockfish.py`
Expected: only the fallback path references `_gap_from_arrow_scores`. `_cp_from_win_pct` is only called from `_gap_from_arrow_scores`.

- [ ] **Step 2: Delete `_cp_from_win_pct`, keep `_gap_from_arrow_scores`**

Remove the `_cp_from_win_pct` function entirely (it's only used by the legacy gap helper, but the legacy helper now lives in the fallback path which doesn't compute a gap from arrow scores — it just emits None on missing WDL).

Actually — the fallback path can still compute a gap from the legacy arrow_score Win% pair. **Decision:** keep both `_cp_from_win_pct` and `_gap_from_arrow_scores`, used only by the missing-WDL fallback. Phase D will revisit this when the worker stops emitting `arrow_score_*`.

So in this task: **no code deletion**. Add a comment near `_cp_from_win_pct`:

```python
# #188 Phase C: kept for missing-WDL fallback. When Phase D drops
# arrow_score_* from the worker payload, _cp_from_win_pct and
# _gap_from_arrow_scores can also go.
```

Add the same `_WIN_PCT_K` keep-note nearby.

- [ ] **Step 3: Commit**

```bash
git add services/app/analysis/derivation/stockfish.py
git commit -m "$(cat <<'EOF'
chore(#188): annotate sigmoid helpers as fallback-only

_cp_from_win_pct + _gap_from_arrow_scores + _WIN_PCT_K stay in
derivation/stockfish.py for the missing-WDL fallback path. Phase D
will revisit when arrow_score_* leaves the worker payload.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C5: Persist `wdl_*_adj` in `complete_stockfish_job`

**Files:**
- Modify: `services/app/analysis/services/jobs.py::complete_stockfish_job`

Phase B wired the column writes already, pulling from `m["wdl_*_adj"]`. Phase C just confirms the values now flow non-null on the WDL path.

- [ ] **Step 1: Write the persistence-with-WDL test**

In `services/app/analysis/tests/test_sf_wdl_persistence.py`, append:
```python
@pytest.mark.django_db
def test_complete_stockfish_job_populates_wdl_adj_on_wdl_path():
    """When the payload carries WDL, _adj columns are non-null (Phase C)."""
    game = Game.objects.create(...)  # reuse fixture
    job = AnalysisJob.objects.create(
        game=game, status=AnalysisJob.STATUS_RUNNING,
        worker_id="w-1", engine="stockfish", depth=20,
    )
    payload = _payload()  # carries WDL
    payload["worker_id"] = "w-1"

    complete_stockfish_job(
        job_id=job.id, worker_id="w-1", key_prefix=None, payload=payload,
    )

    move = MoveAnalysis.objects.get(analysis__game=game, ply=1)
    # Played triple stored verbatim.
    assert (move.wdl_win, move.wdl_draw, move.wdl_loss) == (120, 850, 30)
    # _adj = White-frame mirror (ply 1, White mover → identity).
    assert (move.wdl_win_adj, move.wdl_draw_adj, move.wdl_loss_adj) == (120, 850, 30)


@pytest.mark.django_db
def test_complete_stockfish_job_leaves_wdl_adj_null_on_fallback_path():
    """When the payload lacks WDL, _adj columns stay null (fallback path)."""
    game = Game.objects.create(...)
    job = AnalysisJob.objects.create(
        game=game, status=AnalysisJob.STATUS_RUNNING,
        worker_id="w-1", engine="stockfish", depth=20,
    )
    payload = _payload()
    for k in list(payload["moves"][0]):
        if k.startswith("wdl_"):
            del payload["moves"][0][k]
    payload["worker_id"] = "w-1"

    complete_stockfish_job(
        job_id=job.id, worker_id="w-1", key_prefix=None, payload=payload,
    )

    move = MoveAnalysis.objects.get(analysis__game=game, ply=1)
    assert move.wdl_win is None
    assert move.wdl_win_adj is None
```

Run: `cd services/app && pytest analysis/tests/test_sf_wdl_persistence.py -v -k wdl_adj`
Expected: PASS — no code change needed since Phase B already wired the column writes; the assertions just confirm the new derivation populates them.

- [ ] **Step 2: Commit (test-only addition)**

```bash
git add services/app/analysis/tests/test_sf_wdl_persistence.py
git commit -m "$(cat <<'EOF'
test(#188): wdl_*_adj populated on WDL path, null on fallback

Confirms Phase B's column writes carry the Phase C derivation output:
non-null _adj when payload has WDL, null _adj when payload doesn't.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C6: Golden vectors

**Files:**
- Create: `services/app/analysis/derivation/golden_vectors/sf_wdl_<quiet_game>.json`, `sf_wdl_<tactical_game>.json`
- Create: `services/app/analysis/derivation/tests/test_stockfish_golden_vectors_wdl.py`

- [ ] **Step 1: Generate fixtures from a real Phase-A worker run**

Run the Phase-A worker against two representative PGNs (a quiet positional game + a tactical game with at least one blunder). Capture the full payload via:
```bash
python -m local_worker.analysis.stockfish_cli --pgn <path> --depth 20 --out <fixture>.json
```
(If no CLI exists, write a one-shot script that calls `analyze_pgn` + `build_stockfish_payload` and dumps JSON.)

- [ ] **Step 2: Run derive_sf_game once and pin the output**

```python
import json
from analysis.derivation.stockfish import derive_sf_game

with open("sf_wdl_quiet_input.json") as f:
    payload = json.load(f)
derived = derive_sf_game(payload, game=None)
with open("sf_wdl_quiet_expected.json", "w") as f:
    json.dump(derived, f, indent=2)
```

Manually inspect the output — verify per-side accuracy is in a sensible range (60-95 for the quiet game, lower for the tactical one), and that `wdl_*_adj` columns are populated on every move.

- [ ] **Step 3: Write the golden-vector test**

```python
"""Golden vectors for #188 Phase C — pinned post-WDL derivation outputs."""
import json
from pathlib import Path

import pytest

from analysis.derivation.stockfish import derive_sf_game

GOLDEN_DIR = Path(__file__).parent.parent / "golden_vectors"


@pytest.mark.parametrize("name", ["sf_wdl_quiet", "sf_wdl_tactical"])
def test_sf_wdl_golden_vector(name):
    with open(GOLDEN_DIR / f"{name}_input.json") as f:
        payload = json.load(f)
    with open(GOLDEN_DIR / f"{name}_expected.json") as f:
        expected = json.load(f)
    assert derive_sf_game(payload, game=None) == expected
```

- [ ] **Step 4: Run + commit**

```bash
pytest services/app/analysis/derivation/tests/test_stockfish_golden_vectors_wdl.py -v
git add services/app/analysis/derivation/golden_vectors/sf_wdl_*.json \
        services/app/analysis/derivation/tests/test_stockfish_golden_vectors_wdl.py
git commit -m "$(cat <<'EOF'
test(#188): pin golden vectors for SF WDL-driven derivation

Two new fixtures (quiet + tactical), generated from real Phase-A worker
runs. Confirms _derive_one_move + derive_sf_game produce deterministic
output for the WDL path. Pre-Phase-A cp-only fixtures stay in place to
cover the missing-WDL fallback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C7: PR

```bash
git push -u origin issue/188-sf-wdl-phase-c
gh pr create --title "feat(#188): SF derivation switches to WDL_mu (Phase C)" --body "$(cat <<'EOF'
## Summary
- ``_derive_one_move`` now feeds the Lichess accuracy curve from SF-native ``wdl_mu * 100`` instead of ``win_pct(cp)``, on every move where the worker emits a WDL triple.
- ``wdl_(win|draw|loss)_adj`` columns populated as the White-frame mirror of the mover-frame raw triple. SF rescale is identity — no population rescaling (unlike Lc0).
- Classifier ``second_best_gap`` uses raw mu-gap × ``NormalizeToPawnValue`` × 2 (SF's published scaling rule), not the inverse Lichess sigmoid.
- ``accuracy.win_pct`` retained as a guarded fallback for missing-WDL builds — the only remaining sigmoid call in the SF derivation path.

**Per-side accuracy numbers change for every newly analysed SF game.** Historical games keep their stored accuracy until re-analyzed (re-analyze policy, same as #161).

## Test plan
- [ ] Unit tests in ``test_stockfish_wdl_mu.py`` cover frame mirror, mu, gap × NPV, mate saturation, Black-mover correctness, missing-WDL fallback
- [ ] Persistence tests in ``test_sf_wdl_persistence.py`` confirm ``wdl_*_adj`` populated on WDL path, null on fallback
- [ ] New golden vectors in ``test_stockfish_golden_vectors_wdl.py`` pin two real-game outputs
- [ ] Pre-existing cp-only golden vectors still pass via the fallback path

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

- [ ] Mover/White frame conversion correct on both paths (Black-mover test passes)
- [ ] CPL still cp-based (not switched to mu-based bands)
- [ ] `accuracy.move_accuracy` / `accuracy.game_accuracy` unchanged — they get the same shape input from a different source
- [ ] WDL path leaves no `win_pct(cp)` calls in the per-move output's `wdl_mu`
- [ ] Fallback path leaves `wdl_*_adj` and `wdl_mu` null
- [ ] NPV-missing case defaults to 328 (SF 16+ default) without raising
- [ ] No `chart_data.py` edits in this PR (Phase D)
- [ ] No `_extract_arrows_and_pvs` (worker) edits in this PR (Phase D)
- [ ] Golden vectors regenerated and committed

---

## Out of scope (do not touch in Phase C)

- `chart_data.winpct_payload` refactor (Phase D).
- Removing `arrow_score_*` from the worker payload (Phase D).
- Deleting `accuracy.win_pct` (Phase D; kept as fallback through Phase C).
- Migrating historical analyses (re-analyze policy; documented in PR body).
