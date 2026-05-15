# TensorRT lc0 backend (RunPod L4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run lc0 analysis on the TensorRT backend on RunPod L4 GPUs, building a TRT-enabled lc0 in CI, shipping the TRT runtime libs alongside it, and teaching the worker tuner to calibrate the TRT backend.

**Architecture:** Four ordered phases. Phase A is a small, locally unit-testable change to the worker tuner and is independently mergeable. Phases B–D are infrastructure (CI build, RunPod provisioning scripts) and on-hardware validation — they are verified by CI assertions and an L4 smoke runbook, not unit tests, because TRT engine compilation and nps can only be observed on a real Ada GPU.

**Tech Stack:** lc0 (meson/ninja, `onnx-trt` backend), TensorRT 10.x, CUDA 12.4, GitHub Actions, RunPod pods + network volume, Python (worker tuner), pytest.

**Source design:** GitHub issue #119.

---

## Background facts (verified against the codebase)

- `services/local_worker/local_worker/analysis/lc0.py::_build_engine_opts`
  sets `opts["Backend"] = backend` directly from the backend string — so the
  worker passes whatever `WLW_LC0_BACKEND` is set to straight into lc0's
  `Backend` UCI option. No mapping table to change; only the value and the
  tuner's backend-family logic.
- `services/local_worker/local_worker/analysis/lc0_tuning.py`:
  - `_is_gpu_backend(backend)` → currently True only for `cuda*`, `metal*`,
    `*opencl*`. A TRT backend string falls through to the CPU thread
    heuristic (wrong for a GPU run).
  - `_batch_family(backend)` → returns `"cuda"`/`"metal"`/`None`. A TRT
    backend returns `None`, so `calibrate()` skips the MinibatchSize sweep
    entirely.
  - `_BATCH_SWEEPS` has `cuda` and `metal` families only.
- `.github/workflows/lc0-build.yml` builds `lc0-v<ver>-linux-cuda-fp16.tar.gz`
  (single artifact, no TRT, no bundled libs) on `ubuntu-22.04` + CUDA 12.4.
- `services/local_worker/runpod/runpod_start.sh` downloads
  `lc0-v${LC0_VERSION}-linux-cuda-fp16.tar.gz` to `/workspace/bin/lc0` and
  hard-codes that filename. `LC0_VERSION` default `0.31.2`.
- `services/local_worker/runpod/bootstrap.sh` exports
  `WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-cuda-fp16}"`.
- lc0 TRT backend name: lc0 0.31.x/0.32.x exposes the TensorRT path as the
  **`onnx-trt`** backend. Phase B Task B2 verifies the exact compiled
  backend name from the built binary rather than trusting this note.

---

## Phase A — Worker tuner: recognise + sweep the TRT backend

Independently mergeable. Pure TDD against `test_lc0_tuning.py`.

### Task A1: `_is_gpu_backend` recognises TRT

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0_tuning.py`
- Test: `services/local_worker/tests/test_lc0_tuning.py`

- [ ] **Step 1: Write the failing test**

Append to `services/local_worker/tests/test_lc0_tuning.py`:

```python
def test_heuristics_trt_backend_is_gpu():
    host = HostInfo(
        backend="onnx-trt",
        cpu_count=24,
        ram_total_bytes=_gb(64),
        ram_available_bytes=_gb(40),
    )
    opts = derive_heuristic_opts(host)
    # GPU backends cap Threads at 3; a CPU backend on 24 cores would give 23.
    assert opts["Threads"] == "3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && source .venv/bin/activate && python -m pytest tests/test_lc0_tuning.py::test_heuristics_trt_backend_is_gpu -v`
Expected: FAIL — `Threads` == `"23"` (TRT treated as CPU).

- [ ] **Step 3: Implement**

In `lc0_tuning.py`, edit `_is_gpu_backend`:

```python
def _is_gpu_backend(backend: str) -> bool:
    """True if the backend offloads NN evaluation to a GPU."""
    lower = backend.lower()
    return (
        lower.startswith("cuda")
        or lower.startswith("metal")
        or "opencl" in lower
        or "trt" in lower
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/local_worker && source .venv/bin/activate && python -m pytest tests/test_lc0_tuning.py::test_heuristics_trt_backend_is_gpu -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/local_worker/analysis/lc0_tuning.py services/local_worker/tests/test_lc0_tuning.py
git commit -m "feat(worker): treat trt backend as GPU in tuner heuristics (#119)"
```

### Task A2: `_batch_family` + `_BATCH_SWEEPS` cover TRT

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0_tuning.py`
- Test: `services/local_worker/tests/test_lc0_tuning.py`

- [ ] **Step 1: Write the failing test**

Append to `test_lc0_tuning.py` (mirrors `test_calibrate_metal_uses_smaller_sweep`; `_fake_completed` is already defined in this file):

```python
def test_calibrate_trt_uses_l4_sweep():
    seen_batches: list[int] = []

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        seen_batches.append(mb)
        return _fake_completed("Total: 40000 nps\n")

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "onnx-trt", runner=runner)

    assert result is not None
    assert sorted(seen_batches) == [256, 512, 1024, 2048]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && source .venv/bin/activate && python -m pytest tests/test_lc0_tuning.py::test_calibrate_trt_uses_l4_sweep -v`
Expected: FAIL — `calibrate(... "onnx-trt" ...)` returns `None` (family unknown), `AssertionError` on `result is not None`.

- [ ] **Step 3: Implement**

In `lc0_tuning.py`, add the family to `_BATCH_SWEEPS`:

```python
_BATCH_SWEEPS: dict[str, tuple[int, ...]] = {
    "cuda": (128, 256, 512, 1024),
    "metal": (64, 128, 256),
    # L4 (24 GB, Ada) under TensorRT sustains larger batches than the
    # 12 GB cuda-fp16 rig; the #109 early-regression stop trims doomed
    # large entries on smaller cards.
    "trt": (256, 512, 1024, 2048),
}
```

And extend `_batch_family` (place the TRT check first so `onnx-trt`
never falls through):

```python
def _batch_family(backend: str) -> Optional[str]:
    """Return the key used to look up a MinibatchSize sweep, or None."""
    lower = backend.lower()
    if "trt" in lower:
        return "trt"
    if lower.startswith("cuda"):
        return "cuda"
    if lower.startswith("metal"):
        return "metal"
    return None
```

- [ ] **Step 4: Run the full tuning suite to verify no regression**

Run: `cd services/local_worker && source .venv/bin/activate && python -m pytest tests/test_lc0_tuning.py -v`
Expected: PASS (all existing tests + the two new ones).

- [ ] **Step 5: Update the module docstring changelog**

In `lc0_tuning.py`, add under `Changelog:`:

```
    2026-05-15: Recognise the TensorRT (onnx-trt) backend — GPU thread
        heuristic + a dedicated L4-sized MinibatchSize sweep (issue #119).
```

- [ ] **Step 6: Commit**

```bash
git add services/local_worker/local_worker/analysis/lc0_tuning.py services/local_worker/tests/test_lc0_tuning.py
git commit -m "feat(worker): add trt MinibatchSize sweep family (#119)"
```

### Task A3: Bandit + version bump

**Files:**
- Modify: `services/local_worker/pyproject.toml:7`

- [ ] **Step 1: Bandit scan the edited module**

Run: `cd services/local_worker && source .venv/bin/activate && bandit -ll local_worker/analysis/lc0_tuning.py`
Expected: no Medium/High findings (the edits add no subprocess/eval/IO).

- [ ] **Step 2: Bump worker version**

In `services/local_worker/pyproject.toml`, change `version = "0.9.5"` to
`version = "0.9.6"` (per project rule: any `services/local_worker/` change
bumps the version before tagging a release).

- [ ] **Step 3: Commit**

```bash
git add services/local_worker/pyproject.toml
git commit -m "chore(worker): bump to 0.9.6 for trt tuner support (#119)"
```

---

## Phase B — CI: build TRT-enabled lc0 + bundle runtime libs

Verified by CI job assertions, not unit tests.

### Task B1: Add a `variant` input and TensorRT build deps

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Add a workflow input for the build variant**

Under `workflow_dispatch.inputs`, add:

```yaml
      variant:
        description: "Build variant: cuda-fp16 or trt"
        required: true
        default: "cuda-fp16"
        type: choice
        options:
          - cuda-fp16
          - trt
```

- [ ] **Step 2: Install TensorRT when building the trt variant**

After the existing "Install CUDA toolkit 12.4" step, add:

```yaml
      - name: Install TensorRT (trt variant only)
        if: ${{ inputs.variant == 'trt' }}
        run: |
          sudo apt-get update
          sudo apt-get install -y --no-install-recommends \
            libnvinfer-dev libnvinfer-plugin-dev libnvonnxparsers-dev \
            patchelf
```

(The NVIDIA CUDA apt repo configured by the existing `cuda-keyring`
step also serves the TensorRT packages.)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): add trt build variant input + TensorRT deps (#119)"
```

### Task B2: Verify the TRT backend compiled into the binary

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Add a backend-presence assertion after the build step**

Immediately after the existing "Build lc0" step, add:

```yaml
      - name: Verify TRT backend present (trt variant only)
        if: ${{ inputs.variant == 'trt' }}
        run: |
          cd lc0-src
          BACKENDS="$(./build/lc0 --help 2>&1 || true)"
          echo "$BACKENDS"
          echo "$BACKENDS" | grep -qiE 'onnx-trt|tensorrt' \
            || { echo "FATAL: TRT backend not compiled into lc0"; exit 1; }
```

This fails the job loudly if meson did not detect TensorRT, rather than
shipping a silently CPU/CUDA-only binary. It also records the exact
backend token in the job log (resolves the `onnx-trt` name assumption
for Phase C).

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): assert TRT backend is compiled before packaging (#119)"
```

### Task B3: Package the binary + bundled TRT libs per variant

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Replace the hard-coded packaging step**

Replace the existing "Package binary and checksum" step body with a
variant-aware version that, for `trt`, collects the binary's non-system
shared-lib dependencies into a `lib/` dir inside the tarball:

```yaml
      - name: Package binary and checksum
        run: |
          set -euo pipefail
          VARIANT="${{ inputs.variant }}"
          VER="${{ inputs.lc0_version }}"
          STAGE="$(mktemp -d)"
          cp lc0-src/build/lc0 "${STAGE}/lc0"
          if [ "${VARIANT}" = "trt" ]; then
            mkdir -p "${STAGE}/lib"
            ldd "${STAGE}/lc0" \
              | awk '/=> \//{print $3}' \
              | grep -E 'libnvinfer|libnvonnxparser|libcudnn|libcublas|libcudart' \
              | while read -r so; do cp -Lv "$so" "${STAGE}/lib/"; done
            # Make the binary look in its own ./lib first at runtime.
            patchelf --set-rpath '$ORIGIN/lib' "${STAGE}/lc0"
          fi
          TARBALL="lc0-v${VER}-linux-${VARIANT}.tar.gz"
          tar -czf "${TARBALL}" -C "${STAGE}" .
          sha256sum "${TARBALL}" > "${TARBALL}.sha256"
          echo "TARBALL=${TARBALL}" >> "$GITHUB_ENV"
```

- [ ] **Step 2: Make the publish step variant-aware**

Replace the "Publish release" step's `name` and `files` so both
variants attach to the same `lc0-v<ver>` release without clobbering:

```yaml
      - name: Publish release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: lc0-v${{ inputs.lc0_version }}
          name: lc0 v${{ inputs.lc0_version }}
          body: |
            Auto-built lc0 (${{ inputs.variant }}) for x86_64 Linux.
            Built from upstream tag v${{ inputs.lc0_version }} via
            .github/workflows/lc0-build.yml. SHA256: see attached file.
          files: |
            ${{ env.TARBALL }}
            ${{ env.TARBALL }}.sha256
          fail_on_unmatched_files: true
```

- [ ] **Step 3: Dry-run both variants via workflow_dispatch**

Run (requires `gh` auth and push access):

```bash
gh workflow run lc0-build.yml -f lc0_version=0.31.2 -f variant=cuda-fp16
gh workflow run lc0-build.yml -f lc0_version=0.31.2 -f variant=trt
gh run watch "$(gh run list --workflow=lc0-build.yml -L1 --json databaseId -q '.[0].databaseId')"
```

Expected: both runs green; release `lc0-v0.31.2` has
`lc0-v0.31.2-linux-cuda-fp16.tar.gz` and
`lc0-v0.31.2-linux-trt.tar.gz` (+ `.sha256`). The trt tarball contains
`./lc0` and `./lib/libnvinfer*`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): variant-aware packaging with bundled TRT libs (#119)"
```

---

## Phase C — RunPod provisioning wiring

### Task C1: `runpod_start.sh` — download the selected variant + wire libs

**Files:**
- Modify: `services/local_worker/runpod/runpod_start.sh`

- [ ] **Step 1: Add a variant selector and variant-aware download**

Replace the fixed `LC0_TARBALL`/`LC0_RELEASE_URL` block (the
`lc0-v${LC0_VERSION}-linux-cuda-fp16.tar.gz` lines) with:

```bash
# cuda-fp16 (default) or trt. trt tarballs bundle TensorRT .so files
# under ./lib and the binary is patchelf'd with $ORIGIN/lib rpath.
LC0_VARIANT="${LC0_VARIANT:-cuda-fp16}"
LC0_DIR="/workspace/bin/lc0-${LC0_VARIANT}"
LC0_BIN="${LC0_DIR}/lc0"
LC0_TARBALL="lc0-v${LC0_VERSION}-linux-${LC0_VARIANT}.tar.gz"
LC0_RELEASE_URL="${WLW_LC0_RELEASE_URL:-https://github.com/christophersw/wood_league/releases/download/lc0-v${LC0_VERSION}/${LC0_TARBALL}}"
```

- [ ] **Step 2: Extract into the per-variant dir and export the lib path**

Replace the `mkdir -p /workspace/bin` + download/extract/install block
so it extracts the whole tarball (binary + `lib/`) into `LC0_DIR`:

```bash
mkdir -p "${LC0_DIR}"
if [ ! -x "${LC0_BIN}" ]; then
    log "downloading lc0 ${LC0_VERSION} (${LC0_VARIANT}) from ${LC0_RELEASE_URL}"
    tmpdir="$(mktemp -d)"; cd "${tmpdir}"
    curl -fsSL -o "${LC0_TARBALL}" "${LC0_RELEASE_URL}"
    curl -fsSL -o "${LC0_TARBALL}.sha256" "${LC0_RELEASE_URL}.sha256" || true
    if [ -s "${LC0_TARBALL}.sha256" ]; then
        sha256sum -c "${LC0_TARBALL}.sha256" || { log "FATAL: lc0 sha256 mismatch"; exit 1; }
    fi
    tar -xzf "${LC0_TARBALL}" -C "${LC0_DIR}"
    chmod 0755 "${LC0_BIN}"
    cd /; rm -rf "${tmpdir}"
    log "lc0 installed at ${LC0_BIN}"
else
    log "lc0 already present at ${LC0_BIN} — skipping download"
fi

export WLW_LC0_PATH="${LC0_BIN}"
if [ -d "${LC0_DIR}/lib" ]; then
    export LD_LIBRARY_PATH="${LC0_DIR}/lib:${LD_LIBRARY_PATH:-}"
    log "exported LD_LIBRARY_PATH for bundled TRT libs"
fi
```

- [ ] **Step 3: Shellcheck**

Run: `shellcheck services/local_worker/runpod/runpod_start.sh`
Expected: no new errors (warnings consistent with the existing file).

- [ ] **Step 4: Commit**

```bash
git add services/local_worker/runpod/runpod_start.sh
git commit -m "feat(runpod): variant-aware lc0 download + bundled-lib path (#119)"
```

### Task C2: `bootstrap.sh` — TRT backend default + persistent engine cache

**Files:**
- Modify: `services/local_worker/runpod/bootstrap.sh`

- [ ] **Step 1: Default the backend from the variant**

Replace the `WLW_LC0_BACKEND` export line with a variant-derived default
(operator can still override explicitly):

```bash
LC0_VARIANT="${LC0_VARIANT:-cuda-fp16}"
if [ "${LC0_VARIANT}" = "trt" ]; then
    export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-onnx-trt}"
else
    export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-cuda-fp16}"
fi
```

(The exact backend token is whatever Phase B Task B2's job log printed.
If it differs from `onnx-trt`, use that token here — this step's
default value is the one place it is set.)

- [ ] **Step 2: Persist the TRT engine cache on the volume**

lc0's `onnx-trt` backend recompiles a network-specific TRT engine on
every cold start unless its cache is persisted. After the
`WLW_LC0_BACKEND` block add:

```bash
# TensorRT engine build is multi-minute; persist it on the network
# volume so pod stop/start (and serverless cold start) reuse it.
export WLW_LC0_TRT_CACHE_DIR="${WLW_LC0_TRT_CACHE_DIR:-${DATA_DIR}/trt-cache}"
mkdir -p "${WLW_LC0_TRT_CACHE_DIR}"
```

- [ ] **Step 3: Discover + wire the lc0 TRT cache option (investigation task)**

Determine how the built lc0 exposes the TRT engine-cache path. Run on a
pod (or locally against the trt binary):

```bash
/workspace/bin/lc0-trt/lc0 benchmark --backend=onnx-trt --help 2>&1 | grep -i -E 'cache|engine|trt'
```

Wire the discovered option into the worker's lc0 backend options. The
worker builds backend opts in
`services/local_worker/local_worker/analysis/lc0.py::_build_engine_opts`
— extend it to append the cache option to the `Backend` string (lc0
takes backend sub-options as `backend=onnx-trt(cache=/path)` style) when
`WLW_LC0_TRT_CACHE_DIR` is set. Exact option key comes from the command
above; this task is complete only when step 4 passes.

- [ ] **Step 4: Verify cache reuse on a real pod (pass/fail)**

On an L4 pod with the volume attached, start the pod, run one lc0 job,
stop, start again, run another lc0 job. Inspect both session logs in
`/workspace/logs`:

Expected: the **first** session log shows a TRT engine build (multi-second
TensorRT log lines); the **second** session log shows the engine loaded
from cache with **no** rebuild. If the second build recompiles, the cache
option in step 3 is wrong — iterate step 3.

- [ ] **Step 5: Shellcheck + commit**

Run: `shellcheck services/local_worker/runpod/bootstrap.sh`

```bash
git add services/local_worker/runpod/bootstrap.sh services/local_worker/local_worker/analysis/lc0.py
git commit -m "feat(runpod): trt backend default + volume-persisted TRT cache (#119)"
```

---

## Phase D — On-L4 validation runbook

No code; an operator runbook whose output (the nps numbers) is the
acceptance evidence recorded on issue #119. Not unit-testable by design.

### Task D1: Region + volume preflight

- [ ] Confirm the RunPod network volume's region. The L4 pod/endpoint
  used for TRT **must** be created in that same region (network volumes
  are region-locked). Record the region in issue #119.

### Task D2: A/B nps capture

- [ ] Start an L4 pod with `LC0_VARIANT=cuda-fp16`, run one fixed game
  (known PGN, 25k nodes). From `/workspace/logs`, record: calibration
  `mb=… -> … nps` lines and the `Job … complete (lc0) in …s` line.
- [ ] Start an L4 pod with `LC0_VARIANT=trt` against the same volume and
  the same fixed game. Record the same numbers.
- [ ] Post the cuda-fp16 vs trt nps and per-game seconds to issue #119
  (the acceptance criterion: TRT measured, not assumed).

### Task D3: Persistence confirmation

- [ ] Confirm across a stop/start on the trt pod: no MinibatchSize
  recalibration (tuning cache reused) **and** no TRT engine rebuild
  (TRT cache reused) in the second session log.

---

## Self-Review

**Spec coverage (issue #119 scope 1–5):**
- #119(1) CI TRT build target → Phase B (B1–B3).
- #119(2) bundle TRT runtime libs → Task B3 Step 1.
- #119(3) `runpod_start.sh` download + `LD_LIBRARY_PATH` → Task C1.
- #119(4) `bootstrap.sh` backend + persisted TRT cache → Task C2.
- #119(5) `_BATCH_SWEEPS` trt family → Task A2.
- #119 acceptance (measured TRT vs cuda-fp16, caches persist) → Phase D.
  All five scope items + acceptance map to tasks. No gaps.

**Placeholder scan:** Task C2 Step 3 is an explicit investigation task,
not a placeholder — it has a concrete discovery command and a binary
pass/fail gate (Step 4). All code/YAML/bash steps contain the literal
content to apply. No "TBD"/"handle edge cases"/"similar to" instances.

**Type/identifier consistency:** `LC0_VARIANT`, `LC0_DIR`, `LC0_BIN`,
`WLW_LC0_PATH`, `WLW_LC0_BACKEND`, `WLW_LC0_TRT_CACHE_DIR`, the tarball
name `lc0-v<ver>-linux-<variant>.tar.gz`, and the backend token
`onnx-trt` are used consistently across Phases B/C/D. `_batch_family`,
`_is_gpu_backend`, `_BATCH_SWEEPS`, `calibrate`, `derive_heuristic_opts`,
`HostInfo` match the real symbols verified in the codebase.

**Scope:** Phase A is independently mergeable and shippable on its own
(worker tuner only). Phases B→C→D are strictly ordered (C needs B's
artifact; D needs C). Single cohesive deliverable; not decomposable into
independently-shippable subsystems beyond the A / B-C-D split already
made.
```
