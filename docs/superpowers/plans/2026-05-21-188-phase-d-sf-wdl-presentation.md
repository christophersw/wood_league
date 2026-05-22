# Issue #188 Phase D — Presentation cleanup, drop sigmoid arrows

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> ## 🟢 2026-05-21 refresh — `arrow_score_*` columns survived the reset
>
> The 2026-05-21 fresh-start DB reset (PR #192) attempted to drop `MoveAnalysis.arrow_score_(1|2|3)` and had to restore them mid-PR (`fixup` commit `43d58ad`): 19 active readers still depend on them — `games/services.py`, `games/services_v2.py`, `games/board_builder.py`, the SQLAlchemy service layer (`app/services/stockfish_service.py`, `lc0_service.py`, `analysis_service.py`), plus tests.
>
> Phase D's job is now bigger than originally written: **migrate every reader to consume the new per-candidate WDL columns (`wdl_*_(1|2|3)`) before adding the migration that drops `arrow_score_*`.** Tasks D2/D3 in this plan handle the schema-removal half; you also need to add reader-migration tasks (one per service / template / board-builder consumer) ahead of D3.
>
> Per-candidate WDL persistence lands in #188 Phase B (Task B3 — `complete_stockfish_job` writes the new columns). Do not start Phase D until Phase B has been live long enough that recent analyses actually have populated `wdl_*_(1|2|3)` rows, otherwise consumers will read all-null and the board arrow rendering goes blank.
>
> **Prerequisites:** Phases A, B, C merged. Phase B has run against enough games that `wdl_*_(1|2|3)` is populated on the rows Phase D consumers will read.

**Plan refinement note (still applies):** Re-read merged diffs and reconcile names before executing.

**Goal:** Make the Win% chart payload symmetric between SF and LC0 (both read `wdl_mu * 100`), drop sigmoid arrow scores from the worker, and confirm `accuracy.win_pct` survives only as the documented missing-WDL fallback.

**Architecture:** `chart_data.winpct_payload` reads `wdl_mu` (derived from `wdl_*_adj`) for both engines, deleting the `win_pct(m.cp_eval)` SF branch. Worker `_extract_arrows_and_pvs` returns mover-frame WDL triples instead of sigmoid Win% scalars; `StockfishMoveResult.arrow_score_*` and the corresponding serializer fields are removed (per-candidate WDL triples added in Phase A already carry the equivalent information). Tests confirm `accuracy.win_pct` has exactly one caller after this PR (the documented `_derive_one_move` fallback).

**Tech Stack:** Python 3, Django, DRF, pytest. Worker bumps to `0.13.0`.

---

## Conventions for all tasks (read first)

- **venv:** `source .venv/bin/activate`
- **Quality-gate hook:** active.
- **Test placement:** as in prior phases.
- **Bandit:** `bandit -ll <file>` after every `.py` edit.
- **Worker version bump:** `0.13.0` in `services/local_worker/pyproject.toml` (drops `arrow_score_*` from the payload — breaking for any consumer expecting that field, hence a minor bump).
- **Commit prefix:** `feat(#188):` / `refactor(#188):` / `chore(#188):` + Co-Authored-By trailer.
- **Branch:** `issue/188-sf-wdl-phase-d`.

---

## File Structure

**Modified:**
- `services/app/games/chart_data.py::winpct_payload` — drop SF sigmoid branch.
- `services/app/analysis/derivation/stockfish.py` — switch the classifier's `second_best_gap` to a native cp subtraction of the stored candidate cps (`arrow_cp_1 - arrow_cp_2`, mover frame); then delete `_cp_from_win_pct`, `_gap_from_arrow_scores`, `_WIN_PCT_K`.
- `services/local_worker/local_worker/analysis/stockfish.py::_extract_arrows_and_pvs` — return candidate white-frame cp (already computed as `pv_cp_white`) + drop the sigmoid `arrow_scores` channel.
- `services/local_worker/local_worker/analysis/models.py` — `StockfishMoveResult`: add `arrow_cp_1/2/3`, drop `arrow_score_*`.
- `services/app/api/serializers.py::StockfishMoveSerializer` — add `arrow_cp_1/2/3` (nullable); drop `arrow_score_*` fields + add them to `_FORBIDDEN_PER_MOVE`.
- `services/app/analysis/services/jobs.py` + `derive_sf_game` — pass/write `arrow_cp_*`; stop passing `arrow_score_*`.
- `services/app/analysis/migrations/00YY_*.py` — add `arrow_cp_1/2/3`, drop `arrow_score_1/2/3` on `MoveAnalysis`.
- `services/local_worker/pyproject.toml` — `0.13.0`.

**Created:**
- `services/app/games/tests/test_winpct_payload_symmetric.py` — both engines emit `{ply, winpct, san}` where `winpct = wdl_mu * 100` derived from `wdl_*_adj`.

**Not changed:**
- `accuracy.win_pct` — kept verbatim. The fallback path in `_derive_one_move` is its only caller. A test asserts that.

---

## Task D0: Store SF candidate centipawns → native-cp classifier gap (do FIRST)

> **Why this exists / context (2026-05-21 code review on PR #195):** The SF Brilliant/Great thresholds are cp-denominated (`SF_GREAT_GAP=80`, `SF_BRILLIANT_GAP=150`), but we never store per-candidate cp — only the played move has `cp_eval`. So the classifier gap has always been *reconstructed* from a lossy proxy: legacy via the inverse Lichess sigmoid (`_gap_from_arrow_scores`), and a since-reverted Phase C attempt via `WDL_mu × NPV × 2`. Both back into a number SF computes directly and the worker throws away — in `_extract_arrows_and_pvs`, `pv_cp_white = white_cp(pv_info["score"])` is right there before it's converted to Win% and dropped. Store it instead.
>
> This task must land **before** D2/D3 drop `arrow_score_*`, because once the native-cp gap exists, the arrow-score reconstruction path is what D2/D3/D4 are then free to delete.

**Outcome:** classifier gap = `mover_cp_1 - mover_cp_2` from stored candidate cps, compared natively against `SF_GREAT_GAP`/`SF_BRILLIANT_GAP`. `NormalizeToPawnValue` stays pure metadata. `_gap_from_arrow_scores`, `_cp_from_win_pct`, `_WIN_PCT_K` all delete.

- [ ] **D0.1 Worker — emit candidate cp.** In `_extract_arrows_and_pvs`, return a 4th list of white-frame candidate cp (`pv_cp_white` per PV; `None` for empty slots). Thread through `_analyze_one_move` → `_build_move_result`. Add `arrow_cp_1/2/3: Optional[float]` to `StockfishMoveResult`. Emit in `build_stockfish_payload`. Store **white-frame** to match the `cp_eval` raw convention (#161). Bump worker to `0.13.0` and remember the dual tag (`worker-v0.13.0` + `vast-worker-v0.13.0`).
- [ ] **D0.2 Serializer.** Add `arrow_cp_1/2/3 = FloatField(required=False, allow_null=True, default=None)` to `StockfishMoveSerializer`.
- [ ] **D0.3 Migration.** Add three nullable `FloatField`s `arrow_cp_1/2/3` to `MoveAnalysis` (this CAN be combined with the `arrow_score_*` drop migration in D3, or kept separate — your call).
- [ ] **D0.4 Derivation.** Replace the `_gap_from_arrow_scores(...)` call in `_derive_one_move` with a native helper, e.g. `_gap_from_candidate_cp(move, mover_is_white)` that converts the two white-frame candidate cps to mover frame and returns `max(0.0, mover_cp_1 - mover_cp_2)` (or `None` when either is absent → classifier floors to "Best", same as MultiPV<2 today). Delete `_gap_from_arrow_scores`, `_cp_from_win_pct`, `_WIN_PCT_K`.
- [ ] **D0.5 Persistence.** `complete_stockfish_job` writes `arrow_cp_*`; `derive_sf_game` passes them through.
- [ ] **D0.6 Tests.** Pin: candidate cp persists round-trip; gap = `cp_1 - cp_2` in mover frame for a White AND a Black mover (frame correctness — convert white→mover before subtracting); missing candidate cp → gap `None`. Regenerate the WDL golden vectors if any pinned `classification` shifts under the native-cp gap.

> **Mover-frame note for D0.4:** candidate cps are stored white-frame. For a Black mover, the "better for the mover" line is the one with the *lower* white-frame cp, so convert each to mover frame (`mover_cp = cp if white else -cp`) before subtracting. This is the exact frame step the reconstruction helpers were doing implicitly — get it right and add a Black-mover test (#156-class hazard).

---

## Task D1: Refactor `chart_data.winpct_payload`

**Files:**
- Modify: `services/app/games/chart_data.py`
- Create: `services/app/games/tests/test_winpct_payload_symmetric.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for #188 Phase D — symmetric Win% chart payload."""
from types import SimpleNamespace

from games.chart_data import winpct_payload


def _data(sf_moves, lc0_moves):
    return SimpleNamespace(sf_moves=sf_moves, lc0_moves=lc0_moves)


def _sf_move(ply, wdl_win_adj, wdl_draw_adj, wdl_loss_adj, san="e4", cp_eval=30):
    """Phase-D SF move shape: chart reads wdl_*_adj for Win%."""
    return SimpleNamespace(
        ply=ply, san=san, cp_eval=cp_eval, mate_in=None, classification="Best",
        wdl_win_adj=wdl_win_adj, wdl_draw_adj=wdl_draw_adj, wdl_loss_adj=wdl_loss_adj,
    )


def _lc0_move(ply, wdl_mu, san="e4"):
    return SimpleNamespace(ply=ply, san=san, wdl_mu=wdl_mu)


def test_winpct_payload_sf_reads_wdl_adj():
    sf = [_sf_move(1, 200, 700, 100)]   # mu_white = 0.55 → 55%
    payload = winpct_payload(_data(sf, []))
    assert payload["sf"][0] == {"ply": 1, "winpct": 55.0, "san": "e4"}


def test_winpct_payload_lc0_reads_wdl_mu_unchanged():
    lc0 = [_lc0_move(1, 0.55)]
    payload = winpct_payload(_data([], lc0))
    assert payload["lc0"][0] == {"ply": 1, "winpct": 55.0, "san": "e4"}


def test_winpct_payload_sf_falls_back_when_adj_null():
    """Missing-WDL fallback: sf rows without _adj are dropped from the chart."""
    sf = [SimpleNamespace(
        ply=1, san="e4", cp_eval=30, mate_in=None, classification="Best",
        wdl_win_adj=None, wdl_draw_adj=None, wdl_loss_adj=None,
    )]
    payload = winpct_payload(_data(sf, []))
    assert payload["sf"] == []
```

Run: `cd services/app && pytest games/tests/test_winpct_payload_symmetric.py -v`
Expected: FAIL — current `winpct_payload` calls `win_pct(m.cp_eval)`.

- [ ] **Step 2: Refactor `winpct_payload`**

Replace `services/app/games/chart_data.py::winpct_payload` with:

```python
def winpct_payload(data: GameAnalysisDataV2) -> dict:
    """Build the Win%-chart payload for both engines on a shared 0–100 axis.

    Both branches read ``wdl_mu * 100`` from the engine's stored White-frame
    rescaled triple (``wdl_*_adj`` for SF after #188; ``wdl_mu`` directly for
    LC0). The Lichess sigmoid is gone from this path entirely — SF moves that
    lack a WDL triple (older analyses, missing-WDL fallback) are dropped from
    the chart rather than reconstructed from cp.

    See GitHub issue #188 for the schema-level switch.
    """
    return {
        "sf": [
            {
                "ply": m.ply,
                "winpct": ((m.wdl_win_adj + m.wdl_draw_adj / 2) / 1000.0) * 100.0,
                "san": m.san,
            }
            for m in data.sf_moves
            if m.wdl_win_adj is not None and m.wdl_draw_adj is not None
        ],
        "lc0": [
            {"ply": m.ply, "winpct": (m.wdl_mu or 0.0) * 100.0, "san": m.san}
            for m in data.lc0_moves
            if m.wdl_mu is not None
        ],
    }
```

Drop the `from analysis.derivation.accuracy import win_pct` import if it has no other consumer in this module.

- [ ] **Step 3: Run + commit**

```bash
cd services/app && pytest games/tests/test_winpct_payload_symmetric.py games/tests/ -v
bandit -ll services/app/games/chart_data.py
git add services/app/games/chart_data.py services/app/games/tests/test_winpct_payload_symmetric.py
git commit -m "$(cat <<'EOF'
refactor(#188): winpct_payload reads SF wdl_*_adj — no sigmoid

Both engines now feed the Win% chart from their stored White-frame WDL.
SF: wdl_*_adj → mu*100. LC0: wdl_mu*100 (unchanged).

SF moves without a WDL triple (older analyses, missing-WDL fallback) drop
from the chart rather than reconstructing from cp via the sigmoid.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D2: Drop `arrow_score_*` from the worker payload

**Files:**
- Modify: `services/local_worker/local_worker/analysis/stockfish.py::_extract_arrows_and_pvs`, `build_stockfish_payload`
- Modify: `services/local_worker/local_worker/analysis/models.py::StockfishMoveResult`
- Modify: `services/local_worker/local_worker/analysis/stockfish.py::_build_move_result` — drop the `arrow_scores` parameter

- [ ] **Step 1: Drop sigmoid from `_extract_arrows_and_pvs`**

Change the signature to:
```python
def _extract_arrows_and_pvs(
    info_list: list,
    board: chess.Board,
    mover: chess.Color,
) -> tuple[
    list[str],
    list[Optional[str]],
    list[tuple[Optional[int], Optional[int], Optional[int]]],
]:
```

Body: remove the `arrow_scores` accumulator and `arrow_scores.append(win_pct(mover_cp(...)))` line entirely. Return `arrows, pv_sans, wdl_triples`.

Update the docstring.

- [ ] **Step 2: Update `_build_move_result` + call sites**

Remove the `arrow_scores: list[Optional[float]]` parameter. Remove the three `arrow_score_*` lines from the return constructor.

Update `_analyze_one_move` to drop `arrow_scores` from its unpacking:
```python
    arrows, pv_sans, wdl_candidates = _extract_arrows_and_pvs(
        info_before, board, mover,
    )
```

- [ ] **Step 3: Drop `arrow_score_*` from `StockfishMoveResult`**

In `services/local_worker/local_worker/analysis/models.py`, delete the three `arrow_score_*` fields from the dataclass.

- [ ] **Step 4: Drop `arrow_score_*` from `build_stockfish_payload`**

Remove the three keys from the per-move dict.

- [ ] **Step 5: Drop the `from .math import win_pct` import if now unused**

Drop the `from ._stockfish_helpers import mover_cp, white_cp` import iff `mover_cp` has no other call site (white_cp still used for cp_eval). Verify with: `grep -n "mover_cp\b" services/local_worker/local_worker/analysis/stockfish.py`.

- [ ] **Step 6: Update worker tests**

Any test that asserts `arrow_score_*` in the payload must be removed or updated. Run:
`cd services/local_worker && pytest -v`
Expected: failures point to the now-removed fields. Update or delete the affected assertions.

- [ ] **Step 7: Bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/stockfish.py services/local_worker/local_worker/analysis/models.py
git add services/local_worker/local_worker/analysis services/local_worker/tests
git commit -m "$(cat <<'EOF'
refactor(#188): worker drops sigmoid arrow_score_* in favour of WDL triples

_extract_arrows_and_pvs no longer computes mover-frame Win% from cp;
per-candidate WDL triples (added in Phase A) carry the same signal natively.

StockfishMoveResult + build_stockfish_payload + the SF serializer all
drop arrow_score_(1|2|3). Phase D is the breaking edge — bump worker to
0.13.0 in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D3: Drop `arrow_score_*` server-side

**Files:**
- Modify: `services/app/api/serializers.py::StockfishMoveSerializer` — delete the three fields, add them to `_FORBIDDEN_PER_MOVE`.
- Modify: `services/app/analysis/derivation/stockfish.py::_derive_one_move` — drop arrow_score_* passthrough.
- Modify: `services/app/analysis/services/jobs.py::complete_stockfish_job` — drop arrow_score_* from the MoveAnalysis bulk_create.
- Create: migration `00YY_drop_arrow_scores.py` — drop the three columns from `MoveAnalysis`.

- [ ] **Step 1: Update serializer**

Delete the three `arrow_score_*` field declarations. Add to the existing class attribute:
```python
    _FORBIDDEN_PER_MOVE = frozenset({
        # ... existing ...
        "arrow_score_1", "arrow_score_2", "arrow_score_3",
    })
```

(Inside `StockfishCompleteSerializer._FORBIDDEN_PER_MOVE` — append to the existing frozenset.)

- [ ] **Step 2: Update `_derive_one_move` return**

Delete the three `arrow_score_*` keys from the return dict.

- [ ] **Step 3: Update `complete_stockfish_job`'s bulk_create**

Delete the three `arrow_score_*=m["arrow_score_*"]` kwargs.

- [ ] **Step 4: Generate migration**

```bash
cd services/app && python manage.py makemigrations analysis --name drop_arrow_score_columns
```

- [ ] **Step 5: Drop the model fields**

In `services/app/analysis/models.py::MoveAnalysis`, delete the three `arrow_score_*` field declarations.

- [ ] **Step 6: Apply + run tests**

```bash
cd services/app && DJANGO_ENV=test python manage.py migrate analysis && pytest analysis/ api/ games/ -v -k stockfish
```
Expected: all PASS.

- [ ] **Step 7: Bandit + commit**

```bash
bandit -ll services/app/api/serializers.py services/app/analysis/derivation/stockfish.py services/app/analysis/services/jobs.py services/app/analysis/models.py
git add services/app/
git commit -m "$(cat <<'EOF'
refactor(#188): app drops arrow_score_* columns + serializer fields

MoveAnalysis loses the three legacy mover-frame Win% columns (their signal
is now carried by per-candidate WDL triples added in Phase B). Serializer
treats arrow_score_* as forbidden per-move keys so a stale worker fails
loud rather than silently dropping the field.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D4: Clean the unused sigmoid helpers in derivation

> **Mostly subsumed by Task D0.** If you did D0 first (recommended), `_cp_from_win_pct`, `_gap_from_arrow_scores`, and `_WIN_PCT_K` were already deleted there when the gap switched to native candidate cp. This task then reduces to a confirmation grep. If you skipped D0, do the deletions here — but note the gap then has no source and falls to `None` for every move, which silently disables Brilliant/Great for SF. Prefer D0.

**Files:**
- Modify: `services/app/analysis/derivation/stockfish.py`

- [ ] **Step 1: Confirm the helpers are gone (D0) or delete them**

Confirm `_cp_from_win_pct`, `_gap_from_arrow_scores`, `_WIN_PCT_K` no longer exist (D0 removed them). If D0 was skipped, remove them now — but reconsider doing D0 instead, since a permanently-`None` gap regresses SF classification.

- [ ] **Step 2: Confirm `accuracy.win_pct` is only called from the fallback path**

```bash
grep -rn "from analysis.derivation.accuracy import\|accuracy\.win_pct\|win_pct(" services/app/
```
Expected: hits only in:
- `services/app/analysis/derivation/stockfish.py` (the fallback path inside `_derive_one_move`)
- `services/app/analysis/derivation/accuracy.py` (definition + internal use by `move_accuracy` / `game_accuracy`)
- Tests under `services/app/analysis/derivation/tests/`

If anything else still calls `win_pct(cp)`, raise it in the PR description and decide whether to remove the call site or defer.

- [ ] **Step 3: Add a guard test**

```python
"""Phase D acceptance: accuracy.win_pct only used as missing-WDL fallback."""
import subprocess


def test_win_pct_call_sites_audit():
    """Static-grep proof: no non-fallback win_pct(cp) call in the app."""
    result = subprocess.run(
        ["grep", "-rln", "win_pct(", "services/app/", "--include=*.py"],
        check=True, capture_output=True, text=True,
    )
    files = set(result.stdout.strip().splitlines())
    permitted = {
        "services/app/analysis/derivation/stockfish.py",   # fallback path
        "services/app/analysis/derivation/accuracy.py",    # definition
    }
    # Test files are fine.
    files = {f for f in files if "/tests/" not in f}
    extra = files - permitted
    assert not extra, f"Unexpected win_pct() call sites: {extra}"
```

- [ ] **Step 4: Run + commit**

```bash
cd services/app && pytest analysis/derivation/tests/ -v
bandit -ll services/app/analysis/derivation/stockfish.py
git add services/app/analysis/derivation services/app/analysis/tests
git commit -m "$(cat <<'EOF'
chore(#188): delete unused inverse sigmoid helpers

With arrow_score_* gone from the contract, _cp_from_win_pct,
_gap_from_arrow_scores, and _WIN_PCT_K are all dead. The fallback
path computes the classifier gap as None (→ "Best" floor).

accuracy.win_pct stays — the only remaining caller is the missing-WDL
fallback in _derive_one_move. Static-grep audit test enforces that.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D5: Worker version bump

- [ ] **Step 1: Bump to 0.13.0**

In `services/local_worker/pyproject.toml`, change `version = "0.12.0"` to `version = "0.13.0"`.

- [ ] **Step 2: Commit**

```bash
git add services/local_worker/pyproject.toml
git commit -m "$(cat <<'EOF'
chore(#188): bump wood-league-worker to 0.13.0

Phase D drops arrow_score_(1|2|3) from build_stockfish_payload — breaking
for any consumer that expected the field. Post-merge: tag worker-v0.13.0
(PyPI) + vast-worker-v0.13.0 (ghcr image).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D6: PR

```bash
git push -u origin issue/188-sf-wdl-phase-d
gh pr create --title "feat(#188): symmetric Win% chart + drop SF sigmoid (Phase D)" --body "$(cat <<'EOF'
## Summary
- ``chart_data.winpct_payload`` now reads SF Win% from stored ``wdl_*_adj`` (Phase B columns, populated by Phase C). LC0 branch unchanged. The Lichess sigmoid is gone from the chart code path entirely.
- Worker drops ``arrow_score_(1|2|3)`` from ``_extract_arrows_and_pvs`` and ``build_stockfish_payload`` (per-candidate WDL triples added in Phase A carry the same signal natively).
- Server-side: ``StockfishMoveSerializer`` removes the three legacy fields and forbids them as per-move keys; migration drops the three ``MoveAnalysis`` columns; ``_derive_one_move`` + ``complete_stockfish_job`` stop passing them through.
- ``_cp_from_win_pct`` / ``_gap_from_arrow_scores`` / ``_WIN_PCT_K`` deleted from ``derivation/stockfish.py``. ``accuracy.win_pct`` retained — sole caller is the documented missing-WDL fallback in ``_derive_one_move``. Static-grep audit test enforces this.
- Worker bumped to ``0.13.0``.

Closes #188 with the four-phase rollout: A worker capture → B schema/persistence → C derivation switch → D presentation cleanup.

## Test plan
- [ ] ``test_winpct_payload_symmetric.py`` — both engines read mu*100, SF rows without ``_adj`` drop from the chart
- [ ] Worker tests updated (no ``arrow_score_*`` assertions)
- [ ] Serializer tests confirm ``arrow_score_*`` is rejected as a forbidden per-move key
- [ ] ``test_win_pct_call_sites_audit`` enforces the fallback-only contract
- [ ] Pre-existing SF golden-vector tests still pass (now via WDL path only — the cp-only fixtures from earlier phases can stay or be retired; PR review decides)
- [ ] Post-merge: tag ``worker-v0.13.0`` (PyPI) + ``vast-worker-v0.13.0`` (ghcr)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist

- [ ] `winpct_payload` has no `win_pct(...)` call
- [ ] `accuracy.win_pct` has exactly one app caller (the fallback)
- [ ] `arrow_score_*` removed everywhere: dataclass, serializer (declared + forbidden), model, migration, derivation, persistence, chart, tests
- [ ] Worker tests updated for the new 3-tuple return shape of `_extract_arrows_and_pvs`
- [ ] Static-grep audit test passes
- [ ] Worker bumped to `0.13.0`; PR body lists both tag steps

---

## Out of scope

- Removing `accuracy.win_pct` entirely (kept as fallback).
- Backfill of historical analyses (re-analyze policy).
- LC0 changes (LC0's pipeline is the model we followed, not touched).
- A new arrow-WDL chart in the UI (the candidate WDL columns persist but no UI consumes them yet; that's a follow-up issue).
