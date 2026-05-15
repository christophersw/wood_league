# Worker run cap: claim-one-at-a-time + `--max-jobs`

- **Date:** 2026-05-15
- **Component:** `services/local_worker`
- **Status:** Approved (brainstorming) — pending spec review

## Problem

The worker's `--batch-size` setting (default 5, env `WLW_DEFAULT_BATCH_SIZE`,
clamped 1–10) controls *jobs claimed per checkout call* — a chunk size, not a
run cap. Claiming a chunk reserves up to N jobs on one worker before they are
started, which delays their submission and starves other workers.

Results are already submitted per-job immediately (`run_one_job` calls
`complete_lc0`/`complete_stockfish` right after each game, even inside a
warm-engine batch), so the gap is *claim* behavior, not *submit* behavior.

The desired model:

- Claim exactly one job, analyse it, submit it, then claim the next. Never
  hold reserved-but-unstarted jobs. API chattiness is acceptable.
- A run cap expressed as a **job count**, accepting any positive integer, or
  blank/unset meaning "run until the queue is empty".

## Goals

1. One-at-a-time checkout; no multi-job reservation.
2. New run cap `--max-jobs` (count); blank = run until queue empty.
3. Preserve issue #117's warm lc0 engine reuse (no per-job cold-start).
4. Keep the existing `--batch-time` minutes cap as a coexisting safety
   ceiling (RunPod relies on it).
5. Clean rename — retire `--batch-size` / `WLW_DEFAULT_BATCH_SIZE` with no
   silent behavior flip.

## Non-goals

- TensorRT backend work (tracked separately in issue #119).
- Any change to Stockfish analysis behavior beyond the shared loop refactor.
- A deprecated `--batch-size` alias (explicitly rejected — clean rename).

## Design

### Control flow (per engine)

`run_loop` is restructured to decouple engine lifecycle from claim cadence:

1. Launch the warm engine once at the start of the engine's run (lc0 only;
   Stockfish has no warm engine and is unaffected).
2. Loop:
   - `checkout(count=1)` for this engine.
   - No job returned → queue empty → stop this engine's run.
   - `run_one_job(job, warm_engine)` → result submitted immediately
     (unchanged per-job behavior).
   - Increment a processed-jobs counter.
   - Stop if `processed >= max_jobs` (when `max_jobs` is set), **or** the
     `--batch-time` cap is hit, **or** `stop_event` is set.
3. Quit the warm engine on exit. The existing `_engine_alive` guard still
   relaunches a dead engine mid-run.

Stop conditions are OR'd: whichever of queue-empty, count cap, time cap, or
stop_event fires first ends the run.

### Config / CLI

- Add `Settings.max_jobs: Optional[int]` (default `None`).
- New CLI option `--max-jobs` (typer, `Optional[int]`, default `None`).
- New env var `WLW_MAX_JOBS` → `max_jobs` (parsed like `batch_time_minutes`:
  blank/non-digit → `None`). A parsed value `< 1` (e.g. `0`, negative) is
  treated as unset (`None` → run until queue empty), so a degenerate cap of
  zero can never stop the run before it starts.
- Remove `--batch-size`, `WLW_DEFAULT_BATCH_SIZE`, `Settings.default_batch_size`,
  and the "Batch size (jobs per checkout, 1–10)" interactive prompt.
- Checkout count is hardcoded to 1 (no longer configurable).
- Keep `--batch-time` / `batch_time_minutes` exactly as-is.
- Interactive prompts: replace the batch-size question with
  `Max jobs this run? (blank = until queue empty):`; keep the existing
  batch-time prompt.
- Passing `--batch-size` now produces an "unknown option" error (no alias),
  surfacing the change rather than silently flipping behavior.

### RunPod scripts (same change set)

- `runpod/bootstrap.sh`: both engine launches drop `--batch-size 10`; keep
  `--batch-time 1440` as the 24h safety ceiling. No `--max-jobs` → drain
  until empty, bounded by the time ceiling.
- `runpod/runpod_start.sh`: verify (no `--batch-size` references expected);
  no functional change.
- Worker `README.md` and any docs referencing `--batch-size` /
  `WLW_DEFAULT_BATCH_SIZE` updated to the new flag.

### Tests

- `test_loop.py`: one-at-a-time checkout; warm engine launched once and
  spanning multiple single-job claims; `max_jobs` cap reached stops the run;
  blank `max_jobs` runs until queue empty; count cap + time cap interaction
  (first-to-hit wins); queue-empty stop.
- `test_config_env.py`: `WLW_MAX_JOBS` parsing (int, blank, non-digit);
  removal of `WLW_DEFAULT_BATCH_SIZE`.
- `test_run_command.py`: `--max-jobs` option; `--batch-size` removed;
  interactive prompt wording.

### Versioning

Bump `services/local_worker/pyproject.toml` 0.9.5 → 0.9.6 (changes under
`services/local_worker/`). Release tag follows existing process
(`worker-v0.9.6`).

## Risks

- **RunPod regression:** if `bootstrap.sh` is not updated in the same change,
  the now-unknown `--batch-size 10` aborts both engine processes on a
  headless pod. Mitigation: script + code land together; covered by the
  RunPod-script item above.
- **Warm-engine reuse regression:** if the engine is launched inside the
  per-claim loop instead of once outside it, every job cold-starts. The
  control-flow design hoists the launch above the loop specifically to
  prevent this; a `test_loop.py` assertion that the engine is launched once
  across N single-job claims guards it.

## Acceptance

- Worker claims exactly one job per checkout; no reserved-but-unstarted jobs.
- `--max-jobs N` stops after N completed jobs; blank/unset runs until the
  queue is empty.
- `--batch-time` still caps the run; first cap (or queue-empty) to hit wins.
- One warm lc0 engine spans the whole run (relaunched only on death).
- `--batch-size` / `WLW_DEFAULT_BATCH_SIZE` fully removed; RunPod scripts and
  docs updated; worker version bumped to 0.9.6.
