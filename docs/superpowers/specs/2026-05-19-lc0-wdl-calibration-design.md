# Lc0 WDL Calibration & Draw-Aware Classification — Design

- **Date:** 2026-05-19
- **Status:** Design — awaiting user review
- **Scope:** Sub-project 1 of 2 (analysis pipeline). UI/UX is Sub-project 2 (separate spec).

## 1. Context & Goal

Today the lc0 worker reads the network's raw WDL, derives an objective
`cp_equiv` from Q via the `tan` formula, computes `move_win_delta` from a
single Win% scalar, and classifies moves with Stockfish-shaped labels
(`Brilliant/Great/Best/Excellent/Inaccuracy/Mistake/Blunder`). For a
900–1300 Elo club audience this under-serves the analysis: the network's
superhuman, drawish WDL does not reflect practical club outcomes, and
collapsing the WDL triple to one number discards the *character* of an
error (threw a win into a draw vs. into a loss; sharpened a quiet
position vs. simplified a tense one).

**Goal:** rescale lc0's raw WDL to the players' actual strength using
lc0's WDL-rescale/contempt model, then classify moves on a two-axis
draw-aware scheme (severity × character). Store enough raw input that
every derived number can be recomputed offline without re-running lc0.

## 2. Decomposition

| Sub-project | Contents | Spec |
| --- | --- | --- |
| **SP1 — Analysis pipeline** (this) | raw lc0, network draw-rate calibration, rescale port, draw-aware classification, storage, offline recompute, test infra, wiki docs | this file |
| **SP2 — UI/UX** | surface new severity + character labels in game review, move list, game stats; refresh wiki UX pages | future spec |

Each sub-project gets its own spec → plan → implementation cycle.

## 3. Locked decisions (from brainstorming)

1. **Asymmetric ratings, native lc0 model.** No averaging.
   `WDLCalibrationElo = White's Elo`, `Contempt = WhiteElo − BlackElo`
   (signed), `ContemptMode = white_side_analysis`,
   `WDLEvalObjectivity = 1.0` (analysis: search/move-selection stays
   objective; only WDL output is rescaled).
2. **Draw-rate reference is measured per network, never hardcoded.**
   The earlier 0.58 vs 0.62 conflict is resolved by measurement.
3. **Cache-raw / rescale-in-our-code architecture.** lc0 runs with **no**
   WDL UCI options. The persistent `EvalCache` and cross-game NNCache
   stay keyed `(zobrist, network, nodes)` — player-independent, maximal
   hit rate. The rescale is a pure post-processing transform we own.
4. **Port lc0's rescale rather than use its UCI options.** Forced by
   decisions 3, 5, and 8: native-lc0 calibration would (a) make cached
   evals calibration-specific, collapsing cross-game cache hits, and
   (b) make every future threshold/constant change require a full
   lc0 re-analysis. The transform is small, pure, and closed-form.
5. **Draw-aware 2-axis classification.** Δμ = severity axis;
   ΔD = character axis. Adopt the brainstormed `classify_move_draw_aware`
   gates **verbatim as canonical** (illustrative example numbers in the
   brainstorm are discarded; the function's strict inequalities govern).
6. **Approach A — two orthogonal columns.** One canonical base-severity
   tier; a separate draw-character modifier column. No fused label
   strings; no string parsing for aggregates.
7. **lc0 labels need not match Stockfish.** Divergent label sets are
   desirable — they give the user analytic diversity. Stockfish path is
   untouched.
8. **Store raw inputs + pre-scale model output.** Every classification
   and accuracy number must be a pure function of stored DB fields, so
   thresholds/constants/draw-rate-reference can be retuned offline with
   **no lc0 re-run**.
9. **Clean schema.** DB will be dropped and fully re-analyzed; no
   backfill/migration-compat constraints. No analysis versioning.
10. **Test infrastructure** validating our rescale against lc0's own
    output is in scope (decision this round).
11. **Wiki documentation** (math, analysis-flow, and related pages)
    updated as part of SP1 (decision this round).

## 4. Architecture & Components

### C1 — Worker raw analysis (search unchanged)

`services/local_worker/local_worker/analysis/lc0.py` continues to launch
lc0 with only `Backend/WeightsFile/SyzygyPath` + auto-tuner perf opts. **No**
`WDLCalibrationElo/Contempt/ScoreType/WDLDrawRateReference/WDLEvalObjectivity`
UCI options are set. Per ply we already obtain raw `v = (wins − losses)`
and `d` (draw prob) from `score.pov(...).wdl()`; these raw permille values
are the cache-shareable, reproducible inputs and are stored as-is.

`EvalCache` (`eval_cache.py`) and the cross-game NNCache keys are
**unchanged** — `(zobrist, network, nodes)`. This is the core payoff of
decision 3.

### C2 — Network draw-rate calibration (new)

A calibration routine measures the network's reference draw rate and
persists it keyed by `network_name`, via the existing tuning-sync
persistence path (`lc0_tuning_sync` / `push_after_calibrate`).

Stored record: `{network_name, draw_rate_reference, n_samples,
stderr, measured_at}`.

**Sampling method.** Run lc0 from the start position at default settings,
repeatedly, accumulating the draw permille; stop when the standard error
of the mean draw rate falls below a threshold (default target
`SEM < 0.005`) or a sample cap is hit.

> **Determinism caveat (flag for spec review).** A single start-position
> NN evaluation is *deterministic*; run-to-run variance only arises from
> multi-threaded MCTS node-ordering nondeterminism at a fixed node
> budget. If the worker is configured single-threaded/deterministic,
> repeated startpos runs yield zero variance and the stopping rule never
> trips. The spec therefore defines the sampler as: repeated startpos
> `go nodes=<default>` runs **when** multi-threaded search introduces
> nondeterminism; otherwise fall back to sampling a small curated
> representative opening-position set (first-N plies sampled from
> indexed games) and report its dispersion. **Open item:** confirm the
> fallback set source.

Re-measured only when `network_name` changes. The rescale never runs
without a measured reference for the active network (hard error if
missing — see C8 error handling).

### C3 — Rescale module (new, pure)

A new dependency-light pure module implementing a faithful port of lc0's:

- `WDLRescale(v, d, wdl_rescale_ratio, wdl_rescale_diff, sign, invert, max_reasonable_s)`
- `SimplifiedWDLRescaleParams(contempt, draw_rate_reference, calibration_elo, contempt_max, contempt_attenuation)` → `(ratio, diff)`
- `ConvertRegularToGamePairElo(elo)`

Known constants (to be re-extracted **verbatim** from a pinned lc0
revision during planning): `scale_zero = 15.0`, `elo_slope = 425.0`,
`offset = 6.75`, `transition_sharpness = 250.0`,
`transition_midpoint = 2737.0`, `contempt_max = 420.0` (default),
`contempt_attenuation = 1.0` (default), `eps = 0.0001`, plus the
`log(10)/200` Elo-conversion factor. The verbatim `WDLRescale` body is
captured in Appendix A.

Inputs per game: `WDLCalibrationElo = WhiteElo`,
`Contempt = WhiteElo − BlackElo`, `ContemptMode = white_side_analysis`
(sign/`invert` resolved by side-to-move, mirroring lc0's `ContemptMode::WHITE`
handling for analysis), and the C2-measured `draw_rate_reference` for the
active network. Outputs: rescaled `(W, D, L)` and `μ = W + 0.5·D`.

**Correctness strategy (does not depend on my web-fetch paraphrase):**
the implementation plan pins a specific lc0 source revision, lifts the
three functions verbatim, and is validated by golden tests (C-test) that
run lc0 *with* the WDL options enabled over a fixture of positions and
assert our Python output matches lc0's emitted `WDL_mu`/WDL within a
tight tolerance. lc0-with-options is used **only** as the test oracle,
never in production.

**Two-service constraint.** The worker (`wood-league-worker`, PyPI) and
the Django app are separate deployables with no shared import path. The
pure rescale+classify module is vendored in **both** services and kept
in lockstep by a single shared golden-vector fixture (JSON of
input → expected) checked into both and asserted by each side's test
suite. This fixture is the contract.

### C4 — Draw-aware classification (new)

Replaces lc0's use of `classify_lc0_move` / `_top_tier` (Stockfish path
untouched). Canonical, adopted verbatim:

```
mu_before = W_before + 0.5*D_before          # rescaled, 0–1 scale
mu_after  = W_after  + 0.5*D_after
delta_mu  = mu_before - mu_after             # >0 = winning chances lost
delta_D   = D_after - D_before               # >0 = more drawish

# Base severity tier (one column):
delta_mu <= 0.01 -> Best
delta_mu <= 0.02 -> Excellent
delta_mu <= 0.05 -> Good
delta_mu <= 0.10 -> Inaccuracy
delta_mu <= 0.20 -> Mistake
else             -> Blunder

# Draw-character modifier (separate column; strict inequalities):
delta_mu > 0.10 and delta_D > 0.20  -> "Missed Win"
delta_mu > 0.20 and delta_D < -0.05 -> "Losing Blunder"
delta_mu <= 0.05 and delta_D < -0.20 -> "Risky"
delta_mu <= 0.05 and delta_D > 0.20  -> "Simplification"
else -> none
```

(`Sharpening` is folded into `Risky` per the gates above — the brainstorm
used the terms interchangeably for the "sharpened without losing
advantage" case; one label, one gate.) Brilliant/Great are removed for
lc0: the **classifier** no longer consults SEE / second-best-gap. The
MultiPV candidate **arrows** (`arrow_uci*`, `arrow_score*`, `pv_san*`)
are still computed and stored unchanged — they are UI candidate-move
display, independent of the severity/character labels.

### C5 — Accuracy & aggregate counters

- **Per-side counters** on `Lc0GameAnalysis` are redefined on the new
  base ladder: `blunders = count(Blunder)`, `mistakes = count(Mistake)`,
  `inaccuracies = count(Inaccuracy)`. `Good/Excellent/Best` are not
  counted.
- **Accuracy** is recomputed from the **rescaled** eval: feed the
  existing Lichess `move_accuracy` / `game_accuracy` machinery with
  `Win% = μ·100` (rescaled). The Lichess windowing/harmonic scheme is
  retained; only its Win% input source changes (raw → rescaled μ).
  (**Open item:** confirm reuse of the Lichess curve vs. a bespoke
  rescaled-domain curve.)

### C6 — Persistence & schema (clean rebuild)

`Lc0MoveResult` / `Lc0MoveSerializer` / `Lc0MoveAnalysis` (Django +
SQLAlchemy mirror) per-move fields:

- **Raw model output (pre-scale):** `wdl_win/draw/loss` keep their
  meaning as the *raw* permille triple (cache-shareable, reproducible).
- **Rescaled:** `wdl_win_adj/draw_adj/loss_adj` (permille),
  `wdl_mu` (rescaled μ, e.g. ×1000 int or float — pick one, spec'd).
- **Deltas:** `delta_mu`, `delta_d` (so classification is recomputable
  without re-deriving from neighbouring plies).
- `cp_equiv`: unchanged — objective, from **raw** Q.
- `base_severity` (replaces `classification` for lc0; widen/rename
  column — clean schema, no compat constraint),
  `draw_character` (nullable: Missed Win / Losing Blunder / Risky /
  Simplification / none).

`Lc0GameAnalysis` per-game provenance: `wdl_calibration_elo`,
`contempt`, `draw_rate_reference_used`, `rescale_constants_version`,
`ratings_source` (game record / PGN header / fallback default).

**Invariant:** `{raw WDL triple, per-game provenance}` is sufficient to
recompute every rescaled value, classification, counter, and accuracy
number with zero lc0 involvement (enables C8).

### C7 — Job payload & config plumbing

- Add `white_rating` / `black_rating` to `JobSerializer`
  (`services/app/api/serializers.py`) so the worker can derive
  calibration Elo + contempt.
- Rescale constants (`contempt_max`, `contempt_attenuation`, SEM target,
  sample cap) flow Django settings → job payload, exactly like
  `network_path` / `syzygy_path` do today — but they feed **our** rescale
  module, **not** lc0 setoptions (setting them in lc0 would re-poison the
  shared cache).
- Missing ratings → fall back to a configurable club-midpoint Elo with
  `Contempt = 0`, recorded as `ratings_source = fallback`.

### C8 — App-side recompute command (new)

Django management command re-derives rescaled WDL, deltas,
classifications, counters, and accuracy from stored raw fields +
per-game provenance — no lc0. Used when thresholds/constants/draw-rate
reference change. This is what makes decision 8 pay off. Uses the same
vendored pure module (C3) verified by the shared golden fixture.

## 5. Data flow

```
PGN + white_rating/black_rating (job payload)
  → lc0 raw analyse (cache: zobrist,network,nodes — player-independent)
  → raw (v,d) per ply  ──store raw WDL──┐
  → C2 draw_rate_reference[network]     │
  → C3 rescale(raw, calibElo, contempt) │ store rescaled WDL, μ, Δμ, ΔD
  → C4 classify → base_severity, draw_character
  → C5 counters + accuracy (rescaled μ)
  → API complete payload → DB (+ provenance)

Offline: stored raw + provenance → C3/C4/C5 (recompute cmd) → DB  [no lc0]
```

## 6. Test infrastructure (decision 10)

1. **Golden oracle tests:** a fixture of representative positions
   (varied WDL shapes, asymmetric/symmetric ratings, terminal-adjacent).
   Run lc0 **with** WDL options enabled once to capture ground-truth
   rescaled WDL/`WDL_mu`; assert the Python port matches within tight
   tolerance. Oracle-only; pinned lc0 revision.
2. **Shared golden-vector fixture:** input → expected JSON, asserted by
   *both* worker and app suites — guarantees the two vendored copies
   never drift.
3. **Unit tests:** `WDLRescale` eps-guard branch, `invert`, sign by
   side-to-move, asymmetric/negative contempt, `ConvertRegularToGamePairElo`.
4. **Classification tests:** every base-tier boundary and every
   draw-modifier gate (strict-inequality edges); the brainstorm's
   worked scenarios as regression cases (recomputed, not their
   self-inconsistent headline numbers).
5. **Calibration sampler test:** SEM stopping rule, cap, missing-network
   hard-error path.
6. **Integration:** end-to-end worker job → API → DB with both raw and
   rescaled fields populated; recompute command round-trip
   (recompute = original) on a fixed dataset.

## 7. Error handling & edge cases

- **No measured draw-rate reference for network:** hard error; job
  fails (do not silently fall back to a guessed constant).
- **Missing player ratings:** fallback midpoint Elo, `Contempt = 0`,
  `ratings_source = fallback` recorded.
- **Terminal positions:** existing synthetic-WDL path (#58) feeds the
  rescale like any other (W/D/L); eps-guard in `WDLRescale` returns the
  input unchanged at the 0/1 extremes (mate/forced) — matches lc0.
- **eps-guard parity:** the `eps = 0.0001` early-return must match lc0
  exactly (golden test covers it).
- **Vendored-copy drift:** prevented by the shared golden fixture (CI
  asserts both sides).

## 8. Documentation (decision 11)

Update in the linked wiki (`wood_league.wiki/`):

- `analysis-math.md` — add the WDL rescale/contempt math, the measured
  draw-rate-reference concept, the Δμ/ΔD draw-aware classification
  ladder and modifier gates, and the new accuracy input. Mark the old
  single-Win% lc0 classification as superseded.
- `Architecture-and-Analysis-Flow.md` — raw-cache / rescale-in-code
  flow, calibration step, offline recompute command.
- Cross-link related pages with `[[Page Title]]`; plain
  non-technical tone for prose sections per project wiki conventions.
- SP2 will add the UI-facing label glossary page.

## 9. Rollout

- DB drop + full re-analysis (decision 9). No migration compat.
- `services/local_worker/` changes → bump `version` in
  `services/local_worker/pyproject.toml`; release via
  `git tag worker-v<version>` (publishes `wood-league-worker` to PyPI).
- App-side schema change is a normal Django migration on the rebuilt DB.

## 10. Out of scope (→ SP2)

UI rendering of `base_severity` + `draw_character`, label glossary,
colour/badge treatment, game-review and move-list display, UX wiki page.

## 11. Resolved decisions (owner-delegated, 2026-05-19)

1. **Draw-rate sampler:** repeated startpos `go nodes=<default>` runs
   while multi-threaded search is nondeterministic; if deterministic,
   fall back to a small **curated opening-FEN set bundled with the
   worker** (self-contained, no app-DB coupling). (C2)
2. **Per-side counters:** `blunders=Blunder`, `mistakes=Mistake`,
   `inaccuracies=Inaccuracy`; Good/Excellent/Best uncounted. (C5)
3. **Accuracy:** reuse the existing Lichess `move_accuracy`/
   `game_accuracy` curve fed `Win% = μ·100` from the rescaled eval —
   no bespoke curve. (C5)
4. **`wdl_mu` storage:** `float`. (C6)
5. **Fallback club Elo:** `1100`, exposed as a Django setting
   (default 1100), `Contempt=0`, `ratings_source=fallback`. (C7)

## Appendix A — lc0 `WDLRescale` (verbatim, master)

```cpp
inline double WDLRescale(float& v, float& d, float wdl_rescale_ratio,
                         float wdl_rescale_diff, float sign, bool invert,
                         float max_reasonable_s) {
  if (invert) {
    wdl_rescale_diff = -wdl_rescale_diff;
    wdl_rescale_ratio = 1.0f / wdl_rescale_ratio;
  }
  auto w = (1 + v - d) / 2;
  auto l = (1 - v - d) / 2;
  const float eps = 0.0001f;
  if (w > eps && d > eps && l > eps && w < (1.0f - eps) &&
      d < (1.0f - eps) && l < (1.0f - eps)) {
    auto a = FastLog(1 / l - 1);
    auto b = FastLog(1 / w - 1);
    auto s = 2 / (a + b);
    if (!invert) s = std::min(max_reasonable_s, s);
    auto mu = (a - b) / (a + b);
    auto s_new = s * wdl_rescale_ratio;
    if (invert) {
      std::swap(s, s_new);
      s = std::min(max_reasonable_s, s);
    }
    auto mu_new = mu + sign * s * s * wdl_rescale_diff;
    auto w_new = FastLogistic((-1.0f + mu_new) / s_new);
    auto l_new = FastLogistic((-1.0f - mu_new) / s_new);
    v = w_new - l_new;
    d = std::max(0.0f, 1.0f - w_new - l_new);
    return mu_new;
  }
  return 0;
}
```

**Correction (impl):** the facade applies `WDLRescale` to the **raw NN
eval** and therefore mirrors lc0's `SearchWorker::FetchSingleNodeResult`
path (`src/search/classic/search.cc:2174-2186`) with **`invert=False`**,
sign `= +1` white-to-move / `−1` black-to-move at depth 0 — not the
UCI-display path (L307, `invert=True`). The A5 lc0 oracle is binding.

`SimplifiedWDLRescaleParams` and `ConvertRegularToGamePairElo` are
paraphrased in §C3 from `src/search/classic/params.cc`; the
implementation plan must lift them **verbatim** from the pinned lc0
revision. Golden oracle tests (§6.1) are the binding correctness
guarantee regardless of paraphrase fidelity.
