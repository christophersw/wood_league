# TensorRT lc0 backend (revised: onnx-trt via onnxruntime) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship a TensorRT-capable lc0 for RunPod L4 by enabling lc0's `onnx-trt` backend (onnxruntime TensorRT execution provider), with license-clean public artifacts and a persisted TRT engine cache.

**Architecture:** CI builds lc0 `release/0.32` via lc0's own `./build.sh` against a pinned Microsoft prebuilt `onnxruntime-linux-x64-gpu` release; the public GitHub release bundles only lc0 + onnxruntime libs; NVIDIA TensorRT is fetched at pod-provision time onto the private `/workspace` volume. Verification is empirical: a CI build-integrity gate plus an on-L4 A/B runbook (CI has no GPU).

**Tech Stack:** lc0 (meson via `./build.sh`, `onnx-trt` backend), Microsoft onnxruntime-gpu (CUDA + TensorRT EPs), NVIDIA TensorRT, GitHub Actions, RunPod pods + network volume, bash.

**Source spec:** `docs/superpowers/specs/2026-05-15-trt-lc0-backend-revised-design.md`. **Supersedes** Phases B–D of `docs/superpowers/plans/2026-05-15-trt-lc0-backend.md`. Phase A (worker tuner) is **already done** in PR #120 — not in scope here.

---

## Starting point & baseline (read before Task 1)

- **Branch from the Phase A line, NOT the abandoned worktree branch.** Create the implementation branch from `origin/main` once PR #120 is merged, or from branch `issue/119-trt-tuner-support` (commit `9b4ac09`) if #120 is not yet merged. Do **not** branch from `worktree-issue+119-tensorrt-lc0-backend` — it carries 3 commits (`31d4eba`, `1604a08`, `b0f3361`) implementing the discredited "apt libnvinfer" approach. Those commits are abandoned; this plan rewrites the workflow from the pristine baseline.
- **Pristine baseline of `.github/workflows/lc0-build.yml`** (the version on `main`/`9b4ac09`, 67 lines) has these steps in order: `Checkout repo`, `Install build dependencies`, `Install CUDA toolkit 12.4`, `Clone lc0 source` (`git clone --depth 1 --branch v${{ inputs.lc0_version }} ...`), `Build lc0` (`meson setup build --buildtype=release -Dgtest=false` then `ninja -C build`), `Package binary and checksum` (writes `lc0-v${ver}-linux-cuda-fp16.tar.gz` from `build/lc0`), `Publish release` (`softprops/action-gh-release@v2`, hardcoded cuda-fp16 names). Inputs: only `lc0_version` (string, default `0.31.2`).
- **`services/local_worker/runpod/runpod_start.sh`** baseline: `LC0_VERSION` default `0.9.5`-era `0.31.2`; downloads `lc0-v${LC0_VERSION}-linux-cuda-fp16.tar.gz` to `/workspace/bin/lc0`; exports `WLW_LC0_PATH`.
- **`services/local_worker/runpod/bootstrap.sh`** baseline: exports `WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-cuda-fp16}"`; downloads weights/Syzygy to `/workspace` idempotently with atomic `.part` renames; `DATA_DIR="${WORKSPACE}/data"`.
- venv for any local validation lives in the worktree at `<worktree>/.venv` (pyyaml installed). YAML structural checks use `<worktree>/.venv/bin/python`.

**MANDATORY tooling for implementers/reviewers:** use vexp `run_pipeline`/`get_skeleton` for code understanding (no grep/glob/find/cat — hook-blocked; `Read` for exact files; `git` is fine). For lc0 / onnxruntime / GitHub Actions / `softprops/action-gh-release` / NVIDIA TensorRT facts, use context7 MCP or fetch the exact pinned upstream doc/source URL — **never training memory** (it is stale).

---

## Phase B — CI: build onnx-trt lc0 + license-clean publish

### Task B1: Version/variant inputs + drop the old CUDA-only assumptions

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Replace the `inputs:` block**

Set `on.workflow_dispatch.inputs` to exactly:

```yaml
    inputs:
      lc0_ref:
        description: "lc0 git ref to build (tag/branch), e.g. v0.32.1 or release/0.32"
        required: true
        default: "release/0.32"
      variant:
        description: "Build variant: cuda-fp16 or trt"
        required: true
        default: "cuda-fp16"
        type: choice
        options:
          - cuda-fp16
          - trt
      ort_version:
        description: "Microsoft onnxruntime-gpu release version (trt variant only)"
        required: true
        default: "1.20.1"
```

(`lc0_ref` replaces the old `lc0_version`. `1.20.1` is a starting default; Task B5 pins the exact CUDA/TensorRT-compatible triple.)

- [ ] **Step 2: Update the `Clone lc0 source` step**

Replace its `run:` body with:

```yaml
          git clone --depth 1 --branch ${{ inputs.lc0_ref }} \
            https://github.com/LeelaChessZero/lc0.git lc0-src
```

- [ ] **Step 3: YAML structural check**

Run: `<worktree>/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/lc0-build.yml')); ins=d['on' if 'on' in d else True]['workflow_dispatch']['inputs']; assert set(ins)=={'lc0_ref','variant','ort_version'}, list(ins); assert ins['variant']['type']=='choice'; print('OK', list(ins))"`
Expected: `OK ['lc0_ref', 'variant', 'ort_version']`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): lc0_ref/variant/ort_version inputs for onnx-trt build (#119)"
```

### Task B2: Fetch pinned onnxruntime-gpu for the trt variant

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Insert an onnxruntime-download step**

Immediately AFTER `Install CUDA toolkit 12.4` and BEFORE `Clone lc0 source`, insert:

```yaml
      - name: Fetch onnxruntime-gpu (trt variant only)
        if: ${{ inputs.variant == 'trt' }}
        run: |
          set -euo pipefail
          ORT_VER="${{ inputs.ort_version }}"
          ORT_TGZ="onnxruntime-linux-x64-gpu-${ORT_VER}.tgz"
          curl -fsSL -o "${ORT_TGZ}" \
            "https://github.com/microsoft/onnxruntime/releases/download/v${ORT_VER}/${ORT_TGZ}"
          mkdir -p "${GITHUB_WORKSPACE}/ort"
          tar -xzf "${ORT_TGZ}" --strip-components=1 -C "${GITHUB_WORKSPACE}/ort"
          test -d "${GITHUB_WORKSPACE}/ort/lib" && test -d "${GITHUB_WORKSPACE}/ort/include"
          echo "ORT_DIR=${GITHUB_WORKSPACE}/ort" >> "$GITHUB_ENV"
          ls -1 "${GITHUB_WORKSPACE}/ort/lib"
```

- [ ] **Step 2: YAML structural check**

Run: `<worktree>/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/lc0-build.yml')); s=d['jobs']['build']['steps']; n=[x.get('name') for x in s]; i=n.index('Fetch onnxruntime-gpu (trt variant only)'); assert n[i-1]=='Install CUDA toolkit 12.4' and n[i+1]=='Clone lc0 source', n; print('OK', n)"`
Expected: `OK [...]` with the fetch step between CUDA and Clone.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): fetch pinned onnxruntime-gpu for trt build (#119)"
```

### Task B3: Build via lc0's build.sh with the onnx-trt options

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Replace the `Build lc0` step**

Replace the entire `Build lc0` step with:

```yaml
      - name: Build lc0
        run: |
          set -euo pipefail
          cd lc0-src
          if [ "${{ inputs.variant }}" = "trt" ]; then
            CC=gcc CXX=g++ ./build.sh release \
              -Dgtest=false \
              -Donnx=true \
              -Donnx_libdir="${ORT_DIR}/lib" \
              -Donnx_include="${ORT_DIR}/include" \
              -Ddefault_backend=onnx-trt
          else
            CC=gcc CXX=g++ ./build.sh release -Dgtest=false
          fi
          test -x build/release/lc0
```

Note: `./build.sh` outputs to `build/release/lc0` (NOT `build/lc0` as the
old raw-meson step assumed). All later steps use `build/release/lc0`.

- [ ] **Step 2: YAML check**

Run: `<worktree>/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/lc0-build.yml')); b=[x for x in d['jobs']['build']['steps'] if x.get('name')=='Build lc0'][0]['run']; assert 'build.sh release' in b and 'onnx-trt' in b and 'build/release/lc0' in b, b; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): build via lc0 build.sh with onnx-trt options (#119)"
```

### Task B4: Build-integrity verification (not a GPU run)

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Insert a verify step after `Build lc0`, before packaging**

```yaml
      - name: Verify onnx-trt linked (trt variant only)
        if: ${{ inputs.variant == 'trt' }}
        run: |
          set -uo pipefail
          cd lc0-src
          export LD_LIBRARY_PATH="${ORT_DIR}/lib:${LD_LIBRARY_PATH:-}"
          OUT="$(./build/release/lc0 benchmark --backend=onnx-trt --nodes=1 2>&1 || true)"
          echo "----- lc0 onnx-trt probe output -----"
          echo "$OUT"
          echo "-------------------------------------"
          # FAIL (build is wrong) if the backend is unknown or onnxruntime
          # did not link. PASS if the only failure is the absence of a GPU /
          # network file on the CI runner.
          if echo "$OUT" | grep -qiE "unknown backend|Unknown backend type|error while loading shared libraries|libonnxruntime"; then
            echo "FATAL: onnx-trt not built correctly (backend missing or onnxruntime unlinked)"
            exit 1
          fi
          if echo "$OUT" | grep -qiE "onnx-trt|tensorrt|onnxruntime|Cuda error|no CUDA-capable|Could not find a backend|network file"; then
            echo "OK: binary recognised onnx-trt; failure is GPU/net-absence (expected on CI)"
            exit 0
          fi
          echo "FATAL: unrecognised probe output — pin the expected strings (see Step 2)"
          exit 1
```

- [ ] **Step 2: Pin the real strings from the first trt CI run (investigation, gated)**

This step has no local action. It is completed only by Task B6: after the
first `variant=trt` CI run, read the `Verify onnx-trt linked` step log,
confirm the probe output, and if the generic patterns above mis-classify
the real output, tighten the two `grep -qiE` patterns to the exact
observed substrings (e.g. the precise "no CUDA-capable device" wording lc0
+ onnxruntime emit) and re-run. Done when a `variant=trt` CI run reaches a
**green** Verify step purely on GPU-absence (and a deliberately broken
build — e.g. wrong `onnx_libdir` — makes it red). Record the chosen
substrings in a comment in the step.

- [ ] **Step 3: YAML check + commit**

Run: `<worktree>/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/lc0-build.yml')); n=[x.get('name') for x in d['jobs']['build']['steps']]; i=n.index('Verify onnx-trt linked (trt variant only)'); assert n[i-1]=='Build lc0', n; print('OK', n)"`

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): build-integrity gate for onnx-trt (no GPU) (#119)"
```

### Task B5: License-clean variant packaging + append-safe publish

**Files:**
- Modify: `.github/workflows/lc0-build.yml`

- [ ] **Step 1: Replace `Package binary and checksum`**

```yaml
      - name: Package binary and checksum
        run: |
          set -euo pipefail
          VARIANT="${{ inputs.variant }}"
          REF="${{ inputs.lc0_ref }}"
          SLUG="$(echo "${REF}" | tr '/' '-')"
          STAGE="$(mktemp -d)"
          cp lc0-src/build/release/lc0 "${STAGE}/lc0"
          if [ "${VARIANT}" = "trt" ]; then
            mkdir -p "${STAGE}/lib"
            # Bundle ONLY onnxruntime libs (MIT). Do NOT bundle TensorRT
            # (libnvinfer*) or CUDA libs — TensorRT is fetched to the
            # private volume at pod-provision time; CUDA comes from the
            # RunPod CUDA-runtime image.
            cp -Lv "${ORT_DIR}"/lib/libonnxruntime*.so* "${STAGE}/lib/" 2>/dev/null || true
            test -n "$(ls -A "${STAGE}/lib" 2>/dev/null)" \
              || { echo "FATAL: no onnxruntime libs staged"; exit 1; }
            if ls "${STAGE}"/lib/libnvinfer* >/dev/null 2>&1; then
              echo "FATAL: TensorRT lib leaked into public artifact"; exit 1
            fi
            patchelf --set-rpath '$ORIGIN/lib' "${STAGE}/lc0"
          fi
          TARBALL="lc0-${SLUG}-linux-${VARIANT}.tar.gz"
          tar -czf "${TARBALL}" -C "${STAGE}" .
          sha256sum "${TARBALL}" > "${TARBALL}.sha256"
          echo "TARBALL=${TARBALL}" >> "$GITHUB_ENV"
          echo "RELEASE_TAG=lc0-${SLUG}" >> "$GITHUB_ENV"
```

`patchelf` must be available — add it: in `Install build dependencies`,
append `patchelf` to the existing `apt-get install` list (Step 2).

- [ ] **Step 2: Add patchelf to build deps**

In the `Install build dependencies` step, change the install line to end with `zlib1g-dev patchelf` (append ` patchelf` to the existing package list).

- [ ] **Step 3: Replace `Publish release`**

```yaml
      - name: Publish release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ env.RELEASE_TAG }}
          name: ${{ env.RELEASE_TAG }}
          append_body: true
          body: |
            Auto-built lc0 (${{ inputs.variant }}) for x86_64 Linux from
            ${{ inputs.lc0_ref }} via .github/workflows/lc0-build.yml.
            trt variant bundles onnxruntime (MIT) only; TensorRT is fetched
            to the RunPod volume at provision time. SHA256: see attached.
          files: |
            ${{ env.TARBALL }}
            ${{ env.TARBALL }}.sha256
          fail_on_unmatched_files: true
```

- [ ] **Step 4: YAML check + commit**

Run: `<worktree>/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/lc0-build.yml')); s=d['jobs']['build']['steps']; pub=[x for x in s if x.get('name')=='Publish release'][0]; assert pub['with'].get('append_body') is True, pub['with']; pkg=[x for x in s if x.get('name')=='Package binary and checksum'][0]['run']; assert 'libnvinfer' in pkg and 'onnxruntime' in pkg and 'build/release/lc0' in pkg, 'pkg body'; print('OK')"`
Expected: `OK`.

```bash
git add .github/workflows/lc0-build.yml
git commit -m "ci(lc0): license-clean trt packaging + append-safe publish (#119)"
```

### Task B6: CI dry-run both variants (authorised release publish)

**Coordinator-run, not a subagent. Requires `gh` auth + push access. The user has authorised release publishing.**

- [ ] **Step 1: Push the implementation branch**

```bash
git push -u origin <impl-branch>
```

- [ ] **Step 2: Dry-run cuda-fp16 (regression check)**

```bash
gh workflow run lc0-build.yml --ref <impl-branch> -f lc0_ref=release/0.32 -f variant=cuda-fp16
gh run watch "$(gh run list --workflow=lc0-build.yml -L1 --json databaseId -q '.[0].databaseId')"
```
Expected: green; release `lc0-release-0.32` has `lc0-release-0.32-linux-cuda-fp16.tar.gz` (+ `.sha256`). Confirms `build.sh` + packaging refactor didn't break the existing path.

- [ ] **Step 3: Dry-run trt**

```bash
gh workflow run lc0-build.yml --ref <impl-branch> -f lc0_ref=release/0.32 -f variant=trt -f ort_version=1.20.1
gh run watch "$(gh run list --workflow=lc0-build.yml -L1 --json databaseId -q '.[0].databaseId')"
```
Expected: green. `Verify onnx-trt linked` passes on GPU-absence. Release also has `lc0-release-0.32-linux-trt.tar.gz` (+ `.sha256`); the trt tarball contains `./lc0` + `./lib/libonnxruntime*.so*` and **no** `libnvinfer*`.

- [ ] **Step 4: Resolve B4-Step2 + B5 pinning**

- If Verify mis-classifies the probe output, tighten its grep patterns to the observed substrings (complete Task B4 Step 2), commit, re-run Step 3.
- If the onnxruntime-gpu `ort_version` is incompatible with the CI CUDA toolkit / the L4 driver target, pin a compatible `ort_version` default from onnxruntime's release-notes CUDA/TensorRT table (context7 or the pinned release-notes URL — not memory), update the B1 default, commit, re-run.
- Inspect the trt tarball: `gh release download lc0-release-0.32 -p '*linux-trt*' -D /tmp/relchk && tar -tzf /tmp/relchk/lc0-release-0.32-linux-trt.tar.gz | grep -E 'lib/libonnxruntime|^./lc0$' && ! tar -tzf /tmp/relchk/lc0-release-0.32-linux-trt.tar.gz | grep -q libnvinfer`.

- [ ] **Step 5: Record pinned versions**

Add a comment block at the top of `lc0-build.yml` documenting the verified
working triple: lc0 ref, `ort_version`, and the NVIDIA TensorRT version
that ORT release requires (from ORT release notes). Commit:
`git commit -am "ci(lc0): record verified lc0/ORT/TensorRT version triple (#119)"`.

---

## Phase C — RunPod provisioning

### Task C1: `runpod_start.sh` — variant download + TensorRT fetch + lib path

**Files:**
- Modify: `services/local_worker/runpod/runpod_start.sh`

- [ ] **Step 1: Add variant + version knobs**

Near the existing `LC0_VERSION` definition, add:

```bash
# cuda-fp16 (default) or trt. The trt tarball bundles onnxruntime (MIT)
# under ./lib; TensorRT is fetched separately below (NVIDIA license — not
# redistributed by us).
LC0_VARIANT="${LC0_VARIANT:-cuda-fp16}"
LC0_REF="${LC0_REF:-release/0.32}"
LC0_SLUG="$(echo "${LC0_REF}" | tr '/' '-')"
TRT_VERSION="${TRT_VERSION:-10.4.0.26}"   # must match the ORT build; see lc0-build.yml header
LC0_DIR="/workspace/bin/lc0-${LC0_VARIANT}"
LC0_BIN="${LC0_DIR}/lc0"
LC0_TARBALL="lc0-${LC0_SLUG}-linux-${LC0_VARIANT}.tar.gz"
LC0_RELEASE_URL="${WLW_LC0_RELEASE_URL:-https://github.com/christophersw/wood_league/releases/download/lc0-${LC0_SLUG}/${LC0_TARBALL}}"
```

(`TRT_VERSION` default is a placeholder pending Task B6 Step 5; set it to
the recorded value during C-review.)

- [ ] **Step 2: Replace the download/extract block**

Replace the existing fixed `lc0-...-cuda-fp16` download+install block with:

```bash
mkdir -p "${LC0_DIR}"
if [ ! -x "${LC0_BIN}" ]; then
    log "downloading lc0 ${LC0_REF} (${LC0_VARIANT}) from ${LC0_RELEASE_URL}"
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
```

- [ ] **Step 3: Add the TensorRT volume fetch (trt only)**

After the block above, add:

```bash
TRT_DIR="/workspace/trt"
if [ "${LC0_VARIANT}" = "trt" ]; then
    if [ ! -d "${TRT_DIR}/lib" ]; then
        log "fetching NVIDIA TensorRT ${TRT_VERSION} to ${TRT_DIR}"
        mkdir -p "${TRT_DIR}"
        trt_tmp="$(mktemp -d)"; cd "${trt_tmp}"
        # Pinned NVIDIA TensorRT Linux x86_64 tarball for the CUDA line the
        # RunPod image ships. WLW_TRT_URL overrides for mirror/air-gapped.
        : "${WLW_TRT_URL:?set WLW_TRT_URL to the NVIDIA TensorRT ${TRT_VERSION} linux tarball URL}"
        curl -fL --retry 5 --retry-delay 10 -o trt.tar.gz "${WLW_TRT_URL}"
        tar -xzf trt.tar.gz --strip-components=1 -C "${TRT_DIR}"
        test -d "${TRT_DIR}/lib" || { log "FATAL: TensorRT lib/ missing after extract"; exit 1; }
        cd /; rm -rf "${trt_tmp}"
        log "TensorRT ready at ${TRT_DIR}"
    else
        log "TensorRT already present at ${TRT_DIR} — skipping"
    fi
    export LD_LIBRARY_PATH="${LC0_DIR}/lib:${TRT_DIR}/lib:${LD_LIBRARY_PATH:-}"
fi
```

(`WLW_TRT_URL` is operator-supplied — the exact NVIDIA URL/version is the
recorded value from Task B6 Step 5. This keeps us from hardcoding/guessing
an NVIDIA URL and never republishes TensorRT.)

- [ ] **Step 4: Shellcheck + commit**

Run: `shellcheck services/local_worker/runpod/runpod_start.sh`
Expected: no new errors beyond pre-existing baseline warnings.

```bash
git add services/local_worker/runpod/runpod_start.sh
git commit -m "feat(runpod): variant lc0 + provision-time TensorRT fetch (#119)"
```

### Task C2: `bootstrap.sh` — onnx-trt default + persisted ORT engine cache

**Files:**
- Modify: `services/local_worker/runpod/bootstrap.sh`

- [ ] **Step 1: Variant-derived backend default**

Replace the `WLW_LC0_BACKEND` export line with:

```bash
LC0_VARIANT="${LC0_VARIANT:-cuda-fp16}"
if [ "${LC0_VARIANT}" = "trt" ]; then
    export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-onnx-trt}"
else
    export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-cuda-fp16}"
fi
```

- [ ] **Step 2: Persist the onnxruntime TensorRT engine cache**

After the block above (and after `DATA_DIR` is defined), add:

```bash
# onnxruntime TensorRT EP rebuilds a per-(network,GPU) engine on every
# cold start unless cached. Persist it on the network volume.
if [ "${LC0_VARIANT}" = "trt" ]; then
    export ORT_TENSORRT_ENGINE_CACHE_ENABLE=1
    export ORT_TENSORRT_CACHE_PATH="${WLW_TRT_CACHE_DIR:-${DATA_DIR}/trt-engine-cache}"
    mkdir -p "${ORT_TENSORRT_CACHE_PATH}"
    log "TRT engine cache at ${ORT_TENSORRT_CACHE_PATH}"
fi
```

- [ ] **Step 3: Discovery+verify — does lc0 onnx-trt honour ORT_TENSORRT_* env? (gated by Task D2)**

No local action. lc0's `onnx-trt` backend may consume the onnxruntime TRT
EP options via environment (`ORT_TENSORRT_*`) OR only via a lc0 backend
sub-option string. On the first L4 trt run (Task D2), inspect the lc0
session log: a first run must show a TensorRT engine build; a second
cold start (pod stop/start) must show **engine loaded from cache, no
rebuild**. If the env vars are ignored (rebuild every boot), wire the
cache via the lc0 backend option string in
`services/local_worker/local_worker/analysis/lc0.py::_build_engine_opts`
— append the onnxruntime TRT cache options to the `Backend` value when
`WLW_LC0_BACKEND` is `onnx-trt` and `ORT_TENSORRT_CACHE_PATH` is set
(exact lc0 sub-option syntax confirmed from lc0 onnx backend docs/source
via context7 or the pinned lc0 source URL — not memory). This task is
done only when the Task D3 persistence check passes.

- [ ] **Step 4: Shellcheck + commit**

Run: `shellcheck services/local_worker/runpod/bootstrap.sh`

```bash
git add services/local_worker/runpod/bootstrap.sh
git commit -m "feat(runpod): onnx-trt default + persisted ORT engine cache (#119)"
```

---

## Phase D — On-L4 validation runbook

Coordinator/operator-run. Requires an L4 pod + RunPod creds + the network
volume. Output (the numbers) is the issue #119 acceptance evidence. Not
unit-testable by design.

### Task D1: Region/volume preflight

- [ ] Confirm the network volume's region; the L4 pod must be created in
  that region (network volumes are region-locked). Set `WLW_TRT_URL` to
  the recorded NVIDIA TensorRT URL (Task B6 Step 5) and `TRT_VERSION`
  accordingly. Record region + versions on issue #119.

### Task D2: A/B nps capture

- [ ] Start an L4 pod with `LC0_VARIANT=cuda-fp16`, run one fixed game
  (known PGN, 25k nodes). From `/workspace/logs`, record the calibration
  `mb=… -> … nps` lines and the `Job … complete (lc0) in …s` line.
- [ ] Start an L4 pod with `LC0_VARIANT=trt` (same volume, same game).
  First run is expected to spend minutes building the TensorRT engine —
  note that. Record the same nps + per-game seconds once warm.
- [ ] Post cuda-fp16 vs onnx-trt nps and per-game seconds to issue #119.

### Task D3: Persistence confirmation

- [ ] **Engine-cache activation check (do this on the FIRST trt run).**
  `ORT_TENSORRT_ENGINE_CACHE_ENABLE` / `ORT_TENSORRT_CACHE_PATH` are marked
  **deprecated** in the onnxruntime TensorRT-EP docs
  (https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html);
  the current API is the session-option keys `trt_engine_cache_enable` /
  `trt_engine_cache_path`. They are deprecated, not necessarily removed in
  ORT 1.20.1 — so verify empirically: after the first L4 trt inference,
  `ls -la "${ORT_TENSORRT_CACHE_PATH}"` MUST contain `.engine` (and
  `.profile`) files. If the directory stays empty, lc0 0.32's onnx-trt is
  NOT honouring the env vars → complete Task C2 Step 3 (wire the cache via
  the lc0 onnx-trt backend sub-option string in `lc0.py::_build_engine_opts`,
  exact key confirmed from lc0 onnx backend source) and repeat.
- [ ] Stop/start the trt pod and re-run the fixed game. Confirm in the
  second session log: **no** MinibatchSize recalibration (tuning cache
  reused) **and** **no** TensorRT engine rebuild (the `.engine` files in
  `ORT_TENSORRT_CACHE_PATH` are reused, not regenerated). If a rebuild
  occurs, complete Task C2 Step 3 and repeat.

---

## Self-Review

**Spec coverage (revised spec sections → tasks):**
- CI build/artifact (spec §"CI build + public artifact") → B1–B5; pinned-triple → B6 S5.
- lc0 `release/0.32` via `./build.sh`, onnx options, `default_backend=onnx-trt` → B1, B3.
- Real verification, no `--help` grep → B4 (+ B6 S4 pins strings).
- License-clean public artifact, no TensorRT republished → B5 (explicit `libnvinfer` leak guard) + B6 S4 check.
- `append_body: true` → B5 S3.
- RunPod variant download + provision-time TensorRT fetch + LD_LIBRARY_PATH (spec §"RunPod provisioning") → C1.
- onnx-trt backend default + persisted ORT engine cache (spec §"RunPod runtime") → C2; env-vs-suboption uncertainty → C2 S3 (gated by D3).
- On-L4 region preflight, A/B, persistence (spec §"On-L4 verification") → D1–D3.
- "RunPod base image unchanged / Phase A unaffected" → no task touches the image or the tuner; PR #120 is explicitly out of scope (stated in header).
  No spec requirement is without a task.

**Placeholder scan:** B4-S2, B6, C2-S3, D1–D3 are explicit investigation/empirical tasks — each has a concrete command/method and a binary pass/fail gate (green CI on GPU-absence; tarball lib assertions; second-boot no-rebuild). `TRT_VERSION`/`WLW_TRT_URL`/`ort_version` defaults are placeholders **by necessity** (the exact NVIDIA/ORT version triple is empirically pinned in B6 S5 and threaded into C1/D1) — flagged inline, not silent. No "TODO/handle errors/similar to" placeholders.

**Identifier consistency:** `LC0_VARIANT`, `LC0_REF`/`LC0_SLUG`, `ort_version`/`ORT_DIR`, `TARBALL`/`RELEASE_TAG`, `TRT_DIR`/`TRT_VERSION`/`WLW_TRT_URL`, `ORT_TENSORRT_ENGINE_CACHE_ENABLE`/`ORT_TENSORRT_CACHE_PATH`, the artifact name `lc0-<slug>-linux-<variant>.tar.gz`, and the binary path `build/release/lc0` are used consistently across B/C/D. The slug transform (`tr '/' '-'`) is defined identically in B5 and C1.

**Scope:** Phase B is independently shippable (a TRT-capable lc0 release). C depends on B's artifact; D depends on C. One cohesive deliverable; ordered, not parallel-decomposable.
