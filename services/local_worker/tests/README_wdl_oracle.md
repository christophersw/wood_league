# WDL Calibration lc0 Oracle Procedure

**Status: DEFERRED** — lc0 binary is present on this host (`/opt/homebrew/bin/lc0`)
but no WDL-capable network file (`*.pb.gz`) is available locally.  Run this
procedure in an environment that has both lc0 and a WDL-trained network
(e.g., the vast.ai GPU worker image, which includes BT4-1740).

---

## Purpose

The golden vectors in `wdl_calibration_vectors.json` are derived from the
Python implementation itself (bootstrapped).  The lc0 oracle is the **binding
correctness check**: it verifies that `rescale_wdl` replicates the exact
numbers that lc0 emits when given the same position and engine options.  The
Python path being tested corresponds to lc0's raw-eval path
(`search.cc:2174-2186, invert=False`).

---

## Oracle Procedure

For each `"rescale"` case in `wdl_calibration_vectors.json`:

1. Set up the FEN position for the case (or use the startpos as a proxy if
   no specific FEN is embedded — the rescale is position-independent given
   the raw WDL triple).

2. Start lc0 with these UCI options:

   ```
   setoption name ScoreType value WDL_mu
   setoption name WDLCalibrationElo value <white_elo>
   setoption name Contempt value <white_elo - black_elo>
   setoption name ContemptMode value white_side_analysis
   setoption name WDLEvalObjectivity value 1.0
   setoption name WDLDrawRateReference value <draw_rate_reference>
   ```

3. Feed lc0 the raw `raw_win / raw_draw / raw_loss` values via a custom
   position or by running `go nodes 1` on a position whose network output
   matches the raw triple within floating-point noise.  The intent is to
   compare lc0's final emitted `wdl` and `WDL_mu` fields in the `info`
   line against `rescale_wdl` output.

4. **Acceptance thresholds:**
   - `wdl_white` per-bucket: within 1 permille (≤ 1 unit in 1000 integer
     representation, i.e., `abs(lc0_bucket - py_bucket) <= 1`).
   - `mu`: within `2e-3` (lc0 float32 arithmetic introduces ~1e-5 error;
     the 2e-3 bound accommodates the fast-math approximation chain).

5. Record results in this README under a "Results" heading with the lc0
   network SHA and version used.

---

## Why This Matters

The rescale direction (`invert=False`) is used when lc0 analyses a position
from White's perspective and the caller is White.  The sign-flip path
(`invert=True`) is exercised separately.  The oracle confirms that the
Python port of `SimplifiedWDLRescaleParams` + `WDLRescale` matches lc0
bit-for-bit within the fast-math tolerance.

See `wdl_calibration.py` docstrings and the design doc at
`docs/superpowers/specs/2026-05-19-lc0-wdl-calibration-design.md` for
full derivation details.

---

## Pinned lc0 SHA

The fixture file pins `_lc0_pinned_sha`:
`d8ce48258c39d331c119f8c8729374ceb3df8409`

When running the oracle, confirm lc0 is built from this commit (or a later
commit that does not change `search.cc` WDL rescaling logic) before
treating results as authoritative.

---

## Follow-up Tracking

This deferral is noted in the Task A5 completion report as **DONE_WITH_CONCERNS**.
The follow-up action is: run the oracle on the vast.ai worker environment
and record results here before Task D5 is considered fully closed.
