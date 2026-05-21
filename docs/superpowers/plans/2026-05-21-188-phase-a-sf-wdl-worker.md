# Issue #188 Phase A — Worker emits SF WDL (additive)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture Stockfish's native `UCI_ShowWDL` triple (played-move + per-PV) plus `NormalizeToPawnValue` and ship them through the worker → API payload. App accepts the new fields (validated nullable) but does not persist or derive from them yet — that is Phase B/C/D.

**Architecture:** Additive only. `engine.configure({..., "UCI_ShowWDL": True})` causes python-chess to populate `info["wdl"]` as a `PovWdl` on every `engine.analyse()` result. We extract mover-frame `Wdl(wins, draws, losses)` triples (milli-units summing to ~1000) for the played move and for each of the top-3 MultiPV candidates, persist them through `StockfishMoveResult`, and serialize them in `build_stockfish_payload`. `NormalizeToPawnValue` is read once per `analyze_pgn` call from the engine's UCI option table (default attribute) and persisted on `StockfishGameResult`. Existing `cp_eval` / `arrow_score_*` fields are untouched — both signals coexist for the lifespan of A→B→C; the sigmoid arrow_score goes away in Phase D.

**Tech Stack:** Python 3, python-chess (`chess.engine.SimpleEngine`, `PovWdl`), DRF, pytest.

---

## Conventions for all tasks (read first)

- **venv:** every Python/pytest/bandit command runs after `source .venv/bin/activate` from the repo root (`/Users/christopherwebster/Projects/wood_league`).
- **Quality-gate hook:** per-edit hook hard-fails ruff/mypy/pytest and cyclomatic complexity worse than grade B (tests included). Halstead WARN is non-blocking. Expect transient red between "write failing test" and "implement" steps.
- **Test placement:** worker tests in `services/local_worker/tests/`; Django app tests in `services/app/<app>/tests/test_<mod>.py` packages. `services/app/games/tests.py` is dead/shadowed — never put new tests there.
- **Bandit:** after editing any `.py`, run `bandit -ll <file>`; resolve Medium/High before considering the task done.
- **Worker version bump:** `services/local_worker/pyproject.toml` `version = "0.12.0"` (Task A8). Do not tag in this plan — tagging happens post-merge by the user.
- **Commit messages:** prefix `feat(#188):` / `test(#188):` / `chore(#188):`, end with the trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Work on branch `issue/188-sf-wdl` (created in Task A0).
- **vexp:** use `run_pipeline` / `get_skeleton` to explore — do NOT grep/glob.
- **Subagent model:** default Haiku for file reads and simple edits; Sonnet for derivation/serializer code; never Opus by omission.

## python-chess WDL primer

When `UCI_ShowWDL = True` is set via `engine.configure(...)`, every `engine.analyse(...)` result includes a `PovWdl` at `info["wdl"]`:

```python
povwdl = info["wdl"]                 # chess.engine.PovWdl
wdl_mover = povwdl.pov(board.turn)   # chess.engine.Wdl
wdl_mover.wins, wdl_mover.draws, wdl_mover.losses   # milli-units summing to ~1000
```

For a MultiPV result list, each entry in `info_list` carries its own `wdl` keyed to the side-to-move at the searched root (i.e. mover frame for all entries). Older SF builds without WDL support yield `info.get("wdl") is None`; the extraction helpers in this plan handle that by emitting `None` triples (the schema is nullable end-to-end).

`NormalizeToPawnValue` is a *read-only* UCI option exposed by SF 16+; access via:
```python
opt = engine.options.get("NormalizeToPawnValue")
npv = int(opt.default) if opt is not None else None
```
Older SF builds return `None`; the field is nullable.

---

## File Structure

**Worker (modified):**
- `services/local_worker/local_worker/analysis/stockfish.py` — enable UCI_ShowWDL, extract WDL, thread through `_analyze_one_move` → `_build_move_result`.
- `services/local_worker/local_worker/analysis/models.py` — extend `StockfishMoveResult` / `StockfishGameResult` with WDL + NPV fields.
- `services/local_worker/pyproject.toml` — bump to `0.12.0`.

**Worker (created):**
- `services/local_worker/tests/test_stockfish_wdl.py` — unit tests covering UCI_ShowWDL enablement, played-move WDL capture, per-PV WDL capture, NPV capture, payload shape, fallback when WDL missing.

**App (modified):**
- `services/app/api/serializers.py::StockfishMoveSerializer` — add optional nullable `wdl_(win|draw|loss)` + per-candidate `_1/_2/_3` fields; played triple validated with same `[990, 1010]` sum invariant as Lc0 *iff* present.
- `services/app/api/serializers.py::StockfishCompleteSerializer` — add optional nullable `normalize_to_pawn_value` top-level field.

**App (created):**
- `services/app/api/tests/test_stockfish_wdl_payload.py` — round-trip tests: a payload with WDL fields validates; a payload without WDL fields still validates (backwards compat); a played triple summing to 1500 raises ValidationError; mismatched candidate sums (line 1 has win but missing draw) raises.

**No DB changes in Phase A.** The serializer accepts the fields and the view discards them (until Phase B wires persistence).

---

## Task A0: Branch + worktree setup

**Files:**
- N/A (git only)

- [ ] **Step 1: Cut branch from main**

Run:
```bash
git fetch origin main
git worktree add ../wood_league-188 -b issue/188-sf-wdl origin/main
cd ../wood_league-188
```

- [ ] **Step 2: Sanity-check checkout**

Run: `git status && git log --oneline -3`
Expected: clean tree, HEAD on `issue/188-sf-wdl` at the same commit as `origin/main`.

- [ ] **Step 3: Activate venv**

Run: `source .venv/bin/activate && python -c "import chess.engine; print(chess.engine.PovWdl)"`
Expected: `<class 'chess.engine.PovWdl'>` (confirms python-chess has the WDL types we'll import).

---

## Task A1: Add WDL fields to worker dataclasses

**Files:**
- Modify: `services/local_worker/local_worker/analysis/models.py`

- [ ] **Step 1: Write the failing test**

Create `services/local_worker/tests/test_stockfish_wdl.py`:
```python
"""Tests for #188 Phase A — SF WDL capture."""
from local_worker.analysis.models import StockfishGameResult, StockfishMoveResult


def test_stockfish_move_result_accepts_wdl_triples_nullable():
    move = StockfishMoveResult(
        ply=1, san="e4", fen="...", cp_eval=30,
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    assert move.wdl_win == 120
    assert move.wdl_loss_3 is None  # per-candidate slots default to None


def test_stockfish_game_result_carries_normalize_to_pawn_value():
    result = StockfishGameResult(engine_depth=20, normalize_to_pawn_value=328)
    assert result.normalize_to_pawn_value == 328


def test_stockfish_game_result_defaults_npv_to_none():
    result = StockfishGameResult(engine_depth=20)
    assert result.normalize_to_pawn_value is None
```

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'wdl_win'`.

- [ ] **Step 2: Extend `StockfishMoveResult`**

In `services/local_worker/local_worker/analysis/models.py`, append to `StockfishMoveResult` (after `pv_san_3`):
```python
    # Raw SF WDL triple, mover frame, milli-units (#188 Phase A).
    # Nullable: older SF builds without UCI_ShowWDL or unreachable triples → None.
    wdl_win: Optional[int] = None
    wdl_draw: Optional[int] = None
    wdl_loss: Optional[int] = None
    # Per-candidate raw WDL triples (top 3 MultiPV); fully nullable per line.
    wdl_win_1: Optional[int] = None
    wdl_draw_1: Optional[int] = None
    wdl_loss_1: Optional[int] = None
    wdl_win_2: Optional[int] = None
    wdl_draw_2: Optional[int] = None
    wdl_loss_2: Optional[int] = None
    wdl_win_3: Optional[int] = None
    wdl_draw_3: Optional[int] = None
    wdl_loss_3: Optional[int] = None
```

- [ ] **Step 3: Extend `StockfishGameResult`**

Append after `moves`:
```python
    # Engine build constant captured at analyse time (#188 Phase A).
    # Nullable for older SF builds that don't expose it as a UCI option.
    normalize_to_pawn_value: Optional[int] = None
```

- [ ] **Step 4: Update module docstring Changelog**

In `services/local_worker/local_worker/analysis/models.py`, add to the Changelog block:
```
    2026-05-21 (#188/A): Stockfish dataclasses gained mover-frame WDL triples
        (played move + 3 candidates) plus game-level NormalizeToPawnValue.
        All nullable for older SF builds without UCI_ShowWDL.
```

- [ ] **Step 5: Run the test**

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Bandit**

Run: `bandit -ll services/local_worker/local_worker/analysis/models.py`
Expected: `No issues identified.`

- [ ] **Step 7: Commit**

```bash
git add services/local_worker/local_worker/analysis/models.py services/local_worker/tests/test_stockfish_wdl.py
git commit -m "$(cat <<'EOF'
feat(#188): SF dataclasses gain WDL triples + NormalizeToPawnValue

Phase A scaffolding for SF native WDL: nullable mover-frame triples on
StockfishMoveResult (played + 3 candidates), game-level NPV. No behaviour
change yet — capture wiring lands in subsequent tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A2: Enable UCI_ShowWDL + capture NPV

**Files:**
- Modify: `services/local_worker/local_worker/analysis/stockfish.py` (`_build_engine_opts`, `analyze_pgn`)

- [ ] **Step 1: Write the failing tests**

Append to `services/local_worker/tests/test_stockfish_wdl.py`:
```python
from local_worker.analysis.stockfish import _build_engine_opts


def test_build_engine_opts_enables_uci_showwdl_by_default():
    opts = _build_engine_opts(threads=4, hash_mb=512, syzygy_path="", auto_tune=False)
    assert opts.get("UCI_ShowWDL") is True


def test_build_engine_opts_keeps_caller_overrides_intact():
    """UCI_ShowWDL is additive — it must not displace caller-supplied values."""
    opts = _build_engine_opts(threads=2, hash_mb=128, syzygy_path="", auto_tune=False)
    assert opts["Threads"] == 2 and opts["Hash"] == 128
    assert opts["UCI_ShowWDL"] is True
```

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -k "uci_showwdl or caller_overrides" -v`
Expected: FAIL — both tests fail (`UCI_ShowWDL` not in opts).

- [ ] **Step 2: Enable in `_build_engine_opts`**

In `services/local_worker/local_worker/analysis/stockfish.py`, modify `_build_engine_opts` — append the line `opts.setdefault("UCI_ShowWDL", True)` immediately before `return opts`:

```python
    opts.setdefault("Threads", 4)
    opts.setdefault("Hash", 512)
    # #188 Phase A: ask SF to emit its native WDL triple on every analyse().
    opts.setdefault("UCI_ShowWDL", True)
    return opts
```

- [ ] **Step 3: Capture NPV in `analyze_pgn`**

In `analyze_pgn`, after `engine.configure(opts)` and before the per-move loop, add:
```python
        npv_opt = engine.options.get("NormalizeToPawnValue")
        normalize_to_pawn_value = (
            int(npv_opt.default) if npv_opt is not None and npv_opt.default is not None
            else None
        )
        log.info("stockfish: NormalizeToPawnValue=%s", normalize_to_pawn_value)
```

Change the return statement to:
```python
        return StockfishGameResult(
            engine_depth=depth, engine_name=engine_name, moves=move_results,
            normalize_to_pawn_value=normalize_to_pawn_value,
        )
```

- [ ] **Step 4: Run the tests**

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Smoke-run a real engine**

Run a minimal integration check (skipped if no SF binary):
```bash
python -c "
import os, chess.engine
sf = os.environ.get('STOCKFISH_PATH', '/usr/local/bin/stockfish')
e = chess.engine.SimpleEngine.popen_uci(sf)
try:
    e.configure({'UCI_ShowWDL': True})
    import chess
    info = e.analyse(chess.Board(), chess.engine.Limit(depth=10))
    print('wdl=', info.get('wdl'))
    print('NPV=', e.options.get('NormalizeToPawnValue'))
finally:
    e.quit()
"
```
Expected output includes `wdl= PovWdl(...)` with a non-None triple and a NormalizeToPawnValue Option line. If SF is not installed locally, document the skip in the PR body — CI will run the real test.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/stockfish.py
git add services/local_worker/local_worker/analysis/stockfish.py services/local_worker/tests/test_stockfish_wdl.py
git commit -m "$(cat <<'EOF'
feat(#188): worker enables UCI_ShowWDL + captures NormalizeToPawnValue

_build_engine_opts now sets UCI_ShowWDL=True so every engine.analyse()
result carries info["wdl"]. analyze_pgn reads NormalizeToPawnValue once
from engine.options.default and threads it onto StockfishGameResult.
Nullable end-to-end — older SF builds without these options stay None.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A3: Extract played-move WDL triple

**Files:**
- Modify: `services/local_worker/local_worker/analysis/stockfish.py` (`_analyze_one_move`, `_build_move_result`)

- [ ] **Step 1: Write the failing test**

Append to `test_stockfish_wdl.py`:
```python
import chess
import chess.engine
from unittest.mock import MagicMock

from local_worker.analysis.stockfish import _build_move_result


def test_build_move_result_carries_played_wdl_triple():
    move = _build_move_result(
        san="e4", fen_before="...", cp_eval_after_white=30, mate_in_white=None,
        arrows=["e7e5", "c7c5", ""], arrow_scores=[55.0, 52.0, None],
        pv_sans=["[\"e5\"]", None, None],
        wdl_played=(120, 850, 30),
        wdl_candidates=[(120, 850, 30), (110, 860, 30), (None, None, None)],
    )
    assert (move.wdl_win, move.wdl_draw, move.wdl_loss) == (120, 850, 30)
    assert (move.wdl_win_1, move.wdl_draw_1, move.wdl_loss_1) == (120, 850, 30)
    assert move.wdl_loss_3 is None


def test_build_move_result_handles_missing_wdl():
    move = _build_move_result(
        san="e4", fen_before="...", cp_eval_after_white=30, mate_in_white=None,
        arrows=["e7e5"], arrow_scores=[55.0], pv_sans=[None],
        wdl_played=(None, None, None),
        wdl_candidates=[(None, None, None)],
    )
    assert move.wdl_win is None and move.wdl_draw is None and move.wdl_loss is None
    assert move.wdl_win_1 is None
```

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -k "played_wdl or missing_wdl" -v`
Expected: FAIL — `_build_move_result` doesn't accept `wdl_played` / `wdl_candidates`.

- [ ] **Step 2: Add WDL helper to extract a triple**

In `services/local_worker/local_worker/analysis/stockfish.py`, add a private helper above `_extract_arrows_and_pvs`:

```python
def _wdl_triple_mover(info: dict, mover: chess.Color) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Extract the mover-frame WDL triple from an engine.analyse info dict.

    SF emits WDL only when UCI_ShowWDL was enabled. The returned triple is in
    milli-units (sum ≈ 1000); missing-WDL builds yield (None, None, None).

    Args:
        info: One engine.analyse() result dict.
        mover: Side to move at the searched root.

    Returns:
        (wins, draws, losses) in mover frame, or (None, None, None) when the
        engine did not emit a WDL line.
    """
    povwdl = info.get("wdl")
    if povwdl is None:
        return (None, None, None)
    try:
        wdl = povwdl.pov(mover)
        return (int(wdl.wins), int(wdl.draws), int(wdl.losses))
    except Exception:  # noqa: BLE001
        return (None, None, None)
```

- [ ] **Step 3: Extend `_build_move_result` signature + body**

Replace `_build_move_result` with:

```python
def _build_move_result(
    *,
    san: str,
    fen_before: str,
    cp_eval_after_white: int,
    mate_in_white: Optional[int],
    arrows: list[str],
    arrow_scores: list[Optional[float]],
    pv_sans: list[Optional[str]],
    wdl_played: tuple[Optional[int], Optional[int], Optional[int]],
    wdl_candidates: list[tuple[Optional[int], Optional[int], Optional[int]]],
) -> StockfishMoveResult:
    """Assemble a raw StockfishMoveResult (#161 Phase H + #188 Phase A).

    Args:
        san: SAN of the played move.
        fen_before: FEN before the move was played.
        cp_eval_after_white: White-frame cp evaluation after the move.
        mate_in_white: Signed mate distance (positive = White mates), or None.
        arrows: UCI strings for the top up-to-3 MultiPV candidate moves.
        arrow_scores: Mover-frame Win% for each PV line (legacy raw observable;
            removed in Phase D).
        pv_sans: JSON-encoded SAN continuations for each PV line.
        wdl_played: Mover-frame WDL triple for the played move (any element
            may be None when UCI_ShowWDL is unavailable).
        wdl_candidates: Up to 3 mover-frame WDL triples mirroring ``arrows``.
            Missing slots use (None, None, None).

    Returns:
        StockfishMoveResult with ply=0 (caller sets the real ply_index).
    """
    def _get(seq, idx, default=None):
        return seq[idx] if idx < len(seq) else default

    def _cand(idx):
        triple = _get(wdl_candidates, idx, (None, None, None))
        return triple if triple is not None else (None, None, None)

    c1, c2, c3 = _cand(0), _cand(1), _cand(2)

    return StockfishMoveResult(
        ply=0,
        san=san,
        fen=fen_before,
        cp_eval=cp_eval_after_white,
        mate_in=mate_in_white,
        arrow_uci_1=_get(arrows, 0, "") or "",
        arrow_uci_2=_get(arrows, 1),
        arrow_uci_3=_get(arrows, 2),
        arrow_score_1=_get(arrow_scores, 0),
        arrow_score_2=_get(arrow_scores, 1),
        arrow_score_3=_get(arrow_scores, 2),
        pv_san_1=_get(pv_sans, 0),
        pv_san_2=_get(pv_sans, 1),
        pv_san_3=_get(pv_sans, 2),
        wdl_win=wdl_played[0],
        wdl_draw=wdl_played[1],
        wdl_loss=wdl_played[2],
        wdl_win_1=c1[0], wdl_draw_1=c1[1], wdl_loss_1=c1[2],
        wdl_win_2=c2[0], wdl_draw_2=c2[1], wdl_loss_2=c2[2],
        wdl_win_3=c3[0], wdl_draw_3=c3[1], wdl_loss_3=c3[2],
    )
```

- [ ] **Step 4: Run the tests**

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -v`
Expected: 7 tests PASS.

(Caller updates land in Task A4.)

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/stockfish.py
git add services/local_worker/local_worker/analysis/stockfish.py services/local_worker/tests/test_stockfish_wdl.py
git commit -m "$(cat <<'EOF'
feat(#188): SF _build_move_result accepts WDL played + candidate triples

Adds _wdl_triple_mover helper and extends _build_move_result to populate
the new StockfishMoveResult.wdl_(win|draw|loss)(_1|_2|_3)? fields. Caller
wiring lands in the next commit; this commit is type-shape-only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A4: Wire WDL through `_extract_arrows_and_pvs` and `_analyze_one_move`

**Files:**
- Modify: `services/local_worker/local_worker/analysis/stockfish.py`

- [ ] **Step 1: Write the failing test**

Append to `test_stockfish_wdl.py`:
```python
def test_extract_arrows_and_pvs_returns_wdl_candidates():
    """Each PV slot contributes a mover-frame WDL triple."""
    import chess
    from local_worker.analysis.stockfish import _extract_arrows_and_pvs

    board = chess.Board()
    # Build a fake info_list with python-chess PovScore + PovWdl objects.
    score = chess.engine.PovScore(chess.engine.Cp(30), chess.WHITE)
    wdl_white = chess.engine.PovWdl(chess.engine.Wdl(120, 850, 30), chess.WHITE)
    info = {"pv": [chess.Move.from_uci("e2e4")], "score": score, "wdl": wdl_white}
    arrows, scores, sans, wdl_triples = _extract_arrows_and_pvs(
        [info], board, chess.WHITE,
    )
    assert arrows[0] == "e2e4"
    assert wdl_triples[0] == (120, 850, 30)
```

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -k extract_arrows -v`
Expected: FAIL — `_extract_arrows_and_pvs` returns a 3-tuple, not 4.

- [ ] **Step 2: Extend `_extract_arrows_and_pvs` to return WDL triples**

Modify the signature:
```python
def _extract_arrows_and_pvs(
    info_list: list,
    board: chess.Board,
    mover: chess.Color,
) -> tuple[
    list[str],
    list[Optional[float]],
    list[Optional[str]],
    list[tuple[Optional[int], Optional[int], Optional[int]]],
]:
```

Inside the loop, add WDL extraction parallel to the existing arrow_score capture:
```python
    arrows: list[str] = []
    arrow_scores: list[Optional[float]] = []
    pv_sans: list[Optional[str]] = []
    wdl_triples: list[tuple[Optional[int], Optional[int], Optional[int]]] = []

    for pv_info in info_list[:3]:
        pv = pv_info.get("pv") or []
        if not pv:
            arrows.append("")
            arrow_scores.append(None)
            pv_sans.append(None)
            wdl_triples.append((None, None, None))
            continue

        arrows.append(pv[0].uci())
        pv_cp_white = white_cp(pv_info["score"])
        arrow_scores.append(win_pct(mover_cp(pv_cp_white, mover)))
        wdl_triples.append(_wdl_triple_mover(pv_info, mover))

        pv_board = board.copy()
        pv_san_list: list[str] = []
        for pv_move in pv[:_PV_SAN_DEPTH]:
            try:
                pv_san_list.append(pv_board.san(pv_move))
                pv_board.push(pv_move)
            except Exception:
                break
        pv_sans.append(json.dumps(pv_san_list) if pv_san_list else None)

    return arrows, arrow_scores, pv_sans, wdl_triples
```

Update the docstring to describe the 4th return.

- [ ] **Step 3: Update the call site in `_analyze_one_move`**

Replace the `arrows, arrow_scores, pv_sans = ...` line with:
```python
    arrows, arrow_scores, pv_sans, wdl_candidates = _extract_arrows_and_pvs(
        info_before, board, mover,
    )
```

Then at the end of `_analyze_one_move`, after `board.push(move)` and the `score_after` assignment, capture the played-move WDL from `score_after`'s containing info dict. The matched-PV fast path already has the right dict in hand (it's `info_before[matched_idx]`); the fallback path needs the WDL from the `info_after` call. Restructure:

```python
    if matched_idx is not None:
        score_after = info_before[matched_idx]["score"]
        wdl_played = _wdl_triple_mover(info_before[matched_idx], mover.__invert__() if False else mover)
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
        # After board.push(move), board.turn is the *next* mover. For the played-move
        # WDL we want the just-moved side's frame, which is `mover`.
        wdl_played = _wdl_triple_mover(info_after, mover)
    eval_after_white = white_cp(score_after)
    mate_in_white = _mate_in_from_score(score_after)
```

> **Frame note:** In the matched-PV fast path, the WDL was reported relative to the side whose root is `board` *before* the push — that is, the mover. So `_wdl_triple_mover(..., mover)` is correct. After the push, `info_after`'s root is the new side to move (the opponent of `mover`); `info["wdl"].pov(mover)` correctly recovers the just-moved side's frame.

Simplify the matched path to:
```python
    if matched_idx is not None:
        score_after = info_before[matched_idx]["score"]
        wdl_played = _wdl_triple_mover(info_before[matched_idx], mover)
    else:
        info_after = engine.analyse(board, limit)
        score_after = info_after["score"]
        wdl_played = _wdl_triple_mover(info_after, mover)
```

Pass both into `_build_move_result`:
```python
    return _build_move_result(
        san=move_san,
        fen_before=fen_before,
        cp_eval_after_white=eval_after_white,
        mate_in_white=mate_in_white,
        arrows=arrows,
        arrow_scores=arrow_scores,
        pv_sans=pv_sans,
        wdl_played=wdl_played,
        wdl_candidates=wdl_candidates,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest services/local_worker/tests/ -v`
Expected: all tests PASS, including pre-existing worker tests that exercise `_extract_arrows_and_pvs` / `_analyze_one_move`. If any prior test mocks the 3-tuple return shape, update its expectation to 4-tuple.

- [ ] **Step 5: Bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/stockfish.py
git add services/local_worker/local_worker/analysis/stockfish.py services/local_worker/tests/test_stockfish_wdl.py
git commit -m "$(cat <<'EOF'
feat(#188): wire SF WDL through _extract_arrows_and_pvs + _analyze_one_move

_extract_arrows_and_pvs now returns a per-PV WDL triple list alongside
arrows/scores/sans. _analyze_one_move captures both the played-move WDL
(matched-PV fast path or info_after fallback) and the candidate triples
and threads them into _build_move_result.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A5: Serialize WDL + NPV in `build_stockfish_payload`

**Files:**
- Modify: `services/local_worker/local_worker/analysis/stockfish.py::build_stockfish_payload`

- [ ] **Step 1: Write the failing test**

Append to `test_stockfish_wdl.py`:
```python
from local_worker.analysis.stockfish import build_stockfish_payload


def test_build_stockfish_payload_emits_wdl_and_npv():
    move = StockfishMoveResult(
        ply=1, san="e4", fen="...", cp_eval=30,
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    result = StockfishGameResult(
        engine_depth=20, engine_name="Stockfish 16", moves=[move],
        normalize_to_pawn_value=328,
    )
    payload = build_stockfish_payload(result, worker_id="w-1")
    assert payload["normalize_to_pawn_value"] == 328
    m = payload["moves"][0]
    assert (m["wdl_win"], m["wdl_draw"], m["wdl_loss"]) == (120, 850, 30)
    assert (m["wdl_win_1"], m["wdl_draw_1"], m["wdl_loss_1"]) == (120, 850, 30)
    assert m["wdl_loss_3"] is None


def test_build_stockfish_payload_npv_nullable():
    result = StockfishGameResult(engine_depth=20, moves=[])
    payload = build_stockfish_payload(result, worker_id="w-1")
    assert payload["normalize_to_pawn_value"] is None
```

Run: `pytest services/local_worker/tests/test_stockfish_wdl.py -k "payload" -v`
Expected: FAIL — `normalize_to_pawn_value` not in payload.

- [ ] **Step 2: Update `build_stockfish_payload`**

Replace with:
```python
def build_stockfish_payload(result: StockfishGameResult, *, worker_id: str) -> dict:
    """Serialize a StockfishGameResult into the #161 + #188 raw API payload.

    Args:
        result: StockfishGameResult from analyze_pgn().
        worker_id: Worker identifier string to include in the payload.

    Returns:
        Dict matching StockfishCompleteSerializer's raw-only schema. All
        derivation runs app-side via ``analysis.derivation.stockfish``.
    """
    return {
        "engine": "stockfish",
        "worker_id": worker_id,
        "engine_depth": result.engine_depth,
        "engine_name": result.engine_name,
        # #188 Phase A: SF build-constant captured at analyse time. Nullable
        # for older SF builds that don't expose this UCI option.
        "normalize_to_pawn_value": result.normalize_to_pawn_value,
        "moves": [
            {
                "ply": m.ply,
                "san": m.san,
                "fen": m.fen,
                "cp_eval": m.cp_eval,
                "mate_in": m.mate_in,
                "arrow_uci_1": m.arrow_uci_1,
                "arrow_uci_2": m.arrow_uci_2,
                "arrow_uci_3": m.arrow_uci_3,
                "arrow_score_1": m.arrow_score_1,
                "arrow_score_2": m.arrow_score_2,
                "arrow_score_3": m.arrow_score_3,
                "pv_san_1": m.pv_san_1,
                "pv_san_2": m.pv_san_2,
                "pv_san_3": m.pv_san_3,
                # #188 Phase A: played-move + per-candidate WDL triples,
                # mover frame, milli-units. Fully nullable for missing-WDL builds.
                "wdl_win": m.wdl_win,
                "wdl_draw": m.wdl_draw,
                "wdl_loss": m.wdl_loss,
                "wdl_win_1": m.wdl_win_1,
                "wdl_draw_1": m.wdl_draw_1,
                "wdl_loss_1": m.wdl_loss_1,
                "wdl_win_2": m.wdl_win_2,
                "wdl_draw_2": m.wdl_draw_2,
                "wdl_loss_2": m.wdl_loss_2,
                "wdl_win_3": m.wdl_win_3,
                "wdl_draw_3": m.wdl_draw_3,
                "wdl_loss_3": m.wdl_loss_3,
            }
            for m in result.moves
        ],
    }
```

- [ ] **Step 3: Run tests + commit**

Run: `pytest services/local_worker/tests/ -v`
Expected: all PASS.

```bash
bandit -ll services/local_worker/local_worker/analysis/stockfish.py
git add services/local_worker/local_worker/analysis/stockfish.py services/local_worker/tests/test_stockfish_wdl.py
git commit -m "$(cat <<'EOF'
feat(#188): build_stockfish_payload emits WDL triples + NPV

Phase A payload-shape change: top-level normalize_to_pawn_value plus 12
per-move WDL fields (played + 3 candidates × win/draw/loss). All
nullable; app side validates-but-discards until Phase B persistence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A6: App-side serializer accepts new fields (validated nullable)

**Files:**
- Modify: `services/app/api/serializers.py` (`StockfishMoveSerializer`, `StockfishCompleteSerializer`)
- Create: `services/app/api/tests/test_stockfish_wdl_payload.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for #188 Phase A — app accepts SF WDL fields without persisting."""
import pytest
from rest_framework.exceptions import ValidationError

from api.serializers import StockfishCompleteSerializer


def _minimal_payload(**move_overrides):
    move = {
        "ply": 1, "san": "e4", "fen": "x" * 30, "cp_eval": 30,
        "arrow_uci_1": "e7e5",
    }
    move.update(move_overrides)
    return {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "moves": [move],
    }


def test_payload_validates_without_wdl_fields():
    """Backwards compat: Phase A payloads from older workers must still validate."""
    s = StockfishCompleteSerializer(data=_minimal_payload())
    assert s.is_valid(), s.errors


def test_payload_validates_with_wdl_fields():
    payload = _minimal_payload(
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    payload["normalize_to_pawn_value"] = 328
    s = StockfishCompleteSerializer(data=payload)
    assert s.is_valid(), s.errors
    assert s.validated_data["normalize_to_pawn_value"] == 328
    assert s.validated_data["moves"][0]["wdl_win"] == 120


def test_payload_rejects_played_wdl_with_bad_sum():
    """SF WDL must sum to ~1000 milli when present, mirroring Lc0's validator."""
    payload = _minimal_payload(wdl_win=500, wdl_draw=400, wdl_loss=400)  # sum 1300
    s = StockfishCompleteSerializer(data=payload)
    assert not s.is_valid()
    assert "wdl_win" in s.errors["moves"][0]


def test_payload_accepts_npv_null():
    payload = _minimal_payload()
    payload["normalize_to_pawn_value"] = None
    s = StockfishCompleteSerializer(data=payload)
    assert s.is_valid(), s.errors


def test_payload_partial_wdl_triple_rejected():
    """All-or-nothing per slot: providing wdl_win without wdl_draw/loss is malformed."""
    payload = _minimal_payload(wdl_win=120)  # missing draw + loss
    s = StockfishCompleteSerializer(data=payload)
    assert not s.is_valid()
```

Run: `cd services/app && pytest api/tests/test_stockfish_wdl_payload.py -v`
Expected: FAIL — fields not declared on serializer.

- [ ] **Step 2: Extend `StockfishMoveSerializer`**

In `services/app/api/serializers.py`, add to `StockfishMoveSerializer` (after `pv_san_3`):
```python
    # #188 Phase A: SF native WDL triple (mover frame, milli-units). Nullable
    # end-to-end; older SF builds without UCI_ShowWDL yield (None, None, None).
    wdl_win = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    # Per-candidate triples (top 3 MultiPV); fully nullable per line.
    wdl_win_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_1 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_win_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_2 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_win_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_draw_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
    wdl_loss_3 = serializers.IntegerField(
        min_value=0, max_value=1000, required=False, allow_null=True, default=None,
    )
```

Add a `validate` method to `StockfishMoveSerializer`:
```python
    def validate(self, attrs):
        """Enforce all-or-nothing WDL triple shape + sum invariant when present.

        - Each played/candidate slot must be fully populated or fully None.
        - Populated slots must sum to within [990, 1010] milli (SF rounding).

        Args:
            attrs: Per-move validated fields.

        Returns:
            ``attrs`` unchanged when invariants hold.

        Raises:
            serializers.ValidationError: When a triple is partial or sums out
                of the SF-rounding tolerance.
        """
        for prefix in ("", "_1", "_2", "_3"):
            win = attrs.get(f"wdl_win{prefix}")
            draw = attrs.get(f"wdl_draw{prefix}")
            loss = attrs.get(f"wdl_loss{prefix}")
            slot = (win, draw, loss)
            if all(v is None for v in slot):
                continue
            if any(v is None for v in slot):
                raise serializers.ValidationError({
                    f"wdl_win{prefix}":
                        f"WDL slot {prefix or 'played'} must be all-or-nothing; "
                        f"got partial triple {slot}.",
                })
            total = win + draw + loss
            if total < 990 or total > 1010:
                raise serializers.ValidationError({
                    f"wdl_win{prefix}":
                        f"WDL triple sum {total} out of permitted [990, 1010].",
                })
        return attrs
```

- [ ] **Step 3: Extend `StockfishCompleteSerializer`**

Add the top-level field (alphabetically with the other top-levels):
```python
    # #188 Phase A: SF build constant captured at analyse time, for
    # reproducibility across SF versions. Nullable for older builds.
    normalize_to_pawn_value = serializers.IntegerField(
        min_value=1, max_value=99999, required=False, allow_null=True, default=None,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd services/app && pytest api/tests/test_stockfish_wdl_payload.py -v`
Expected: all 5 PASS.

- [ ] **Step 5: Re-run the existing serializer tests for regressions**

Run: `cd services/app && pytest api/tests/test_serializers_raw_payload.py api/tests/test_complete_endpoint_derives.py -v`
Expected: all PASS — the new fields are optional so the existing payloads still validate.

- [ ] **Step 6: Bandit + commit**

```bash
bandit -ll services/app/api/serializers.py
git add services/app/api/serializers.py services/app/api/tests/test_stockfish_wdl_payload.py
git commit -m "$(cat <<'EOF'
feat(#188): app StockfishCompleteSerializer accepts WDL + NPV (nullable)

Mirror the Lc0 WDL slot shape on Stockfish: played-triple + 3 candidate
triples on StockfishMoveSerializer, top-level normalize_to_pawn_value on
StockfishCompleteSerializer. All optional/nullable for backwards compat
with pre-Phase-A workers. Per-slot all-or-nothing + sum invariant enforced.
Phase A does not persist these — Phase B wires the migration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A7: Worker version bump

**Files:**
- Modify: `services/local_worker/pyproject.toml`

- [ ] **Step 1: Bump version**

Locate the `[project]` section and change:
```toml
version = "0.11.0"   # or whatever the current value is
```
to:
```toml
version = "0.12.0"
```

- [ ] **Step 2: Commit**

```bash
git add services/local_worker/pyproject.toml
git commit -m "$(cat <<'EOF'
chore(#188): bump wood-league-worker to 0.12.0

Phase A: emits SF WDL triples + NormalizeToPawnValue. Backwards
compatible — app accepts but does not yet persist.

Post-merge: tag `worker-v0.12.0` to publish to PyPI, then
`vast-worker-v0.12.0` to build the ghcr image vast pulls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task A8: PR

**Files:** N/A

- [ ] **Step 1: Push the branch**

Run:
```bash
git push -u origin issue/188-sf-wdl
```

- [ ] **Step 2: Create the PR**

```bash
gh pr create --title "feat(#188): capture SF WDL triples + NormalizeToPawnValue (Phase A)" --body "$(cat <<'EOF'
## Summary
- Worker enables ``UCI_ShowWDL=true``, captures mover-frame WDL triples for the played move and each of the top-3 MultiPV candidates, and reads ``NormalizeToPawnValue`` from SF's UCI options.
- Worker payload (``build_stockfish_payload``) gains 12 per-move WDL fields + one top-level ``normalize_to_pawn_value``.
- App ``StockfishCompleteSerializer`` accepts all new fields as nullable, with the same per-slot all-or-nothing + sum-in-[990,1010] invariant as Lc0.
- Phase A only — no schema change, no derivation change. Sigmoid ``arrow_score_*`` and cp-based math stay untouched and continue to drive the chart / classification stack.

This is the first PR of four for #188. Phase B (schema + persistence), Phase C (derivation → WDL_mu), Phase D (presentation cleanup) land in follow-up PRs.

## Test plan
- [ ] Unit tests in ``services/local_worker/tests/test_stockfish_wdl.py``
- [ ] Serializer tests in ``services/app/api/tests/test_stockfish_wdl_payload.py``
- [ ] Existing ``test_serializers_raw_payload.py`` / ``test_complete_endpoint_derives.py`` still pass (backwards compat)
- [ ] Local smoke run against a real SF 16+ binary confirms ``info["wdl"]`` is populated and ``NormalizeToPawnValue`` is read (default 328 for SF 16)
- [ ] Post-merge: tag ``worker-v0.12.0`` (PyPI) + ``vast-worker-v0.12.0`` (ghcr image)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review checklist (the executor runs this before opening the PR)

- [ ] All new fields nullable end-to-end (dataclass → payload → serializer)
- [ ] Per-slot all-or-nothing invariant fires for partial triples in serializer tests
- [ ] Sum-in-[990,1010] invariant fires for malformed WDL in serializer tests
- [ ] `_wdl_triple_mover` returns `(None, None, None)` when `info["wdl"]` is absent
- [ ] Matched-PV fast path frame is correct (mover before push, not after)
- [ ] No reference to `wdl_win` / `wdl_draw` / `wdl_loss` in Phase B/C/D code paths (those are subsequent PRs — should be zero diff outside the files listed here)
- [ ] Worker version bumped to 0.12.0
- [ ] Bandit clean on every edited `.py`
- [ ] PR body mentions both dual-tag steps post-merge

---

## Out of scope (do not implement in Phase A)

- Schema migration (`MoveAnalysis.wdl_*` columns) — Phase B.
- `derive_sf_game` reading WDL — Phase B persistence + Phase C math.
- `chart_data.winpct_payload` reading WDL — Phase D.
- Removing `_cp_to_winpct`, `_cp_from_win_pct`, `_WIN_PCT_K`, `arrow_score_*` — Phase C/D.
- `accuracy.win_pct` deletion — Phase D (kept as guarded missing-WDL fallback).
- Backfill of historical analyses — out of scope for #188 entirely (re-analyze policy, same as #161).
