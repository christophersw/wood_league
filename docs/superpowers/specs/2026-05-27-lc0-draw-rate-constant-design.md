# Lc0 Draw Rate — Constant Cutover + Contempt Sign Confirmation

**Date:** 2026-05-27
**Status:** Spec, pending implementation
**Related memory:** [[project_lc0_wdl_calibration_159]], [[project_engines_emit_raw_161]], [[project_worker_dual_tag]]

## Motivation

The Lc0 worker currently measures a per-network `draw_rate_reference` by
sampling a fixed FEN set, persists it server-side in `NetworkCalibration`,
and pre-flights every checkout against a `(network_name, settings_hash)`
calibration row. The pipeline carries non-trivial complexity (sampler,
settings hash, `NeedsCalibration` exception, calibration submit API,
disk-side `lc0_tuning.json` push/pull) for a value that, in practice, we
want to pin at `0.62` for our single production network (BT4-it332).

Separately, a question came up about whether the WDL/contempt calibration
is computed for the correct perspective. The current code computes a
single White-side pass (`WDLCalibrationElo = white_elo`,
`Contempt = white_elo − black_elo`, `ContemptMode = white_side_analysis`).
That matches the canonical Lc0 invocation and the WDL output for one side
is the inverse of the other (W↔L swap, D stays), so no second pass is
needed. This spec confirms that and adds a one-line docstring/comment so
the invariant is captured in code.

## Goals

1. Replace the live per-network draw-rate measurement with a single
   worker-side constant `LC0_DRAW_RATE_REFERENCE = 0.62` paired with the
   network configuration.
2. Delete the `NetworkCalibration` table, the `NeedsCalibration` flow,
   the calibration submission API/serializers, and the worker-side
   sampler entirely.
3. Confirm in code (via a brief comment) that the existing
   `contempt = white_elo − black_elo` math is correct for the
   `white_side_analysis` mode the rest of the pipeline uses.

## Non-Goals

- Adding a Black-side analysis pass. (Inverted WDL = same information.)
- Schema or behavior changes to `Lc0Analysis` / `Lc0Move` derivation
  beyond receiving a constant value.
- Multi-network support. If we later add a second network, the constant
  can be promoted to a `{network_name: draw_rate}` mapping in the same
  module.

## Design

### App side

- **Delete `NetworkCalibration`** model and its admin/exports
  (`services/app/analysis/models.py:584-621` and references).
- **Delete `calibration_hash.py`** (settings-hash computation no longer
  used).
- **Delete `_resolve_lc0_calibration` and `NeedsCalibration`** from
  `analysis/services/jobs.py`. The `pre_claim_checkout` branch that
  raises `NeedsCalibration` is removed; lc0 checkouts no longer
  pre-flight calibration.
- **Drop the `draw_rate_reference` field** from the checkout response
  (Lc0 jobs no longer carry it — the worker supplies it from its own
  constant on the engine-done leg).
- **Delete the calibration submission endpoint** (`submit_network_calibration`
  in `api/views.py` and its serializer in `api/serializers.py`).
- **Migration:** `DropModel(NetworkCalibration)` in
  `services/app/analysis/migrations/`.
- **Derivation unchanged:** `analysis/derivation/lc0.py` and
  `_calibration.py` continue to consume `draw_rate_reference` from the
  payload — they always see `0.62`.
- **Contempt comment:** add a one-line note above
  `"contempt": white_elo - black_elo` in
  `analysis/derivation/lc0.py:360` stating the perspective invariant:
  `WDLCalibrationElo = white_elo`, `Contempt = white_elo − black_elo`,
  `ContemptMode = white_side_analysis`. Negative contempt = White is
  the underdog.

### Worker side

- **New module `services/local_worker/local_worker/analysis/lc0_calibration.py`**
  exporting `LC0_DRAW_RATE_REFERENCE = 0.62` with a comment naming the
  network it was measured against (BT4-1024x15x32h-swa-6147500-policytune-332).
- **Delete files:**
  - `analysis/lc0_draw_rate.py`
  - `analysis/draw_rate_fens.py`
  - `commands/calibrate_draw_rate_cmd.py`
  - Tests whose sole purpose is the calibration flow:
    `tests/test_lc0_draw_rate.py`,
    `tests/test_loop_needs_calibration.py`,
    `tests/test_submit_network_calibration.py`,
    `tests/test_checkout_needs_calibration.py`
    (final list confirmed during implementation).
- **`cli.py`:** drop the `calibrate-draw-rate` typer subcommand
  registration and its import.
- **`loop.py`:** delete the `measure_draw_rate` import (line 57) and the
  `_calibrate_for_checkout` helper (around line 83-110) plus the
  `NeedsCalibration` catch in the main loop.
- **`worker_client/client.py`:** remove `NeedsCalibration` parsing.
- **`analysis/lc0.py`:** change `analyze_pgn()` default for
  `draw_rate_reference` to read from
  `lc0_calibration.LC0_DRAW_RATE_REFERENCE`; remove the
  `_get_or_measure_draw_rate` path and the `lc0_tuning.json` push/pull
  of draw-rate keys.
- **`lc0_tuning_sync.py`:** drop draw-rate fields from the synced
  tuning file.

### Wire protocol

- Checkout response: `draw_rate_reference` removed for lc0 jobs.
- Engine-done payload: worker still sends `draw_rate_reference` (now
  always `0.62`), so the existing derivation path is unchanged.

## Migration notes

- `DropModel(NetworkCalibration)` is destructive. Per the
  `project_db_fresh_start_2026_05_21` memory, the DB was recreated
  recently; loss of historical calibration rows is acceptable.
- No backfill needed — `Lc0Analysis.draw_rate_reference` is the
  per-game stored value and was already populated at derivation time.

## Release

- Bump `services/local_worker/pyproject.toml` minor version.
- Tag both `worker-v<v>` (PyPI) and `vast-worker-v<v>` (ghcr image) per
  [[project_worker_dual_tag]] to avoid a "manifest unknown" pull failure
  on vast.

## Testing

- Unit: keep an `analyze_pgn` integration test that asserts the
  per-job payload contains `draw_rate_reference == 0.62`.
- App side: tests covering `_resolve_lc0_calibration` and
  `NeedsCalibration` are removed with the code.
- Quality gate: run the full pipeline (ruff → bandit+semgrep →
  radon/xenon → mypy → pytest+cov) after each side's edits.

## Workflow

1. Open `upgrade`-labeled GitHub issue with this design summarised.
2. Branch `issue/<n>-lc0-draw-rate-constant` from `main`.
3. Implement app side (model drop + migration + jobs/api/serializer
   cleanup).
4. Implement worker side (constant module + file/CLI/loop deletions +
   `analyze_pgn` default).
5. Run quality gate.
6. PR back to `main`. Post-merge: tag worker dual release.
