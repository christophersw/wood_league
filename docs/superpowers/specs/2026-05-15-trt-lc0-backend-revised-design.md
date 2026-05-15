# TensorRT lc0 backend — revised design (onnx-trt via onnxruntime)

- **Date:** 2026-05-15
- **Components:** `.github/workflows/lc0-build.yml`, `services/local_worker/runpod/runpod_start.sh`, `services/local_worker/runpod/bootstrap.sh`, `services/local_worker/local_worker/analysis/lc0.py`
- **Status:** Approved (brainstorming) — pending spec review
- **Supersedes:** the CI/provisioning portion of `docs/superpowers/plans/2026-05-15-trt-lc0-backend.md` (Phases B–D). Phase A of that plan (worker tuner) is unaffected and already in **PR #120**.
- **Related:** issue #119

## Why this revision exists

The original plan (#119 / `2026-05-15-trt-lc0-backend.md`) assumed apt-installing
`libnvinfer-dev` would give lc0 a TensorRT backend. A pre-merge review
established this is false, and the pinned lc0 source confirms it:

- lc0 `release/0.32` (commit `d8ce482`, `meson_options.txt` + `README.md`)
  has **no standalone native TensorRT backend**. TensorRT is reachable only
  through the **`onnx-trt`** backend, which is an **onnxruntime execution
  provider**. README: "Lc0 offers several ONNX based backends, namely
  onnx-cpu, onnx-cuda, **onnx-trt**, onnx-rocm … utilizing the execution
  providers offered by onnxruntime."
- The onnx backend is gated on onnxruntime via the `onnx`, `onnx_libdir`
  (`/usr/lib/`), `onnx_include` (`/usr/include/onnxruntime/`) meson options.
  README: those same options accept an unpacked prebuilt onnxruntime
  release from `microsoft/onnxruntime/releases`.
- `onnx-trt` is registered unconditionally in lc0, so a `lc0 --help` grep
  is **not** a valid "TRT works" gate.

## Decisions (locked during brainstorming)

1. **lc0 version:** target `release/0.32`, pinned to the exact latest
   0.32.x tag. CI input defaults to that tag. (Matches production worker
   logs which run lc0 v0.32.1.)
2. **TRT path:** `onnx-trt` via Microsoft's prebuilt
   `onnxruntime-linux-x64-gpu` (ships the TensorRT + CUDA execution
   providers). No building onnxruntime from source.
3. **Distribution / licensing split:** the public GitHub release tarball
   bundles only license-clean bits — the lc0 binary (GPL + NVIDIA-linking
   exception) and the onnxruntime `.so` set (MIT). **NVIDIA TensorRT libs
   are NOT republished by us**; they are fetched at pod-provision time
   directly from NVIDIA onto the private `/workspace` network volume (same
   pattern as Syzygy/weights).
4. **RunPod base image:** unchanged — keep the stock
   `nvidia/cuda:*-runtime` image and the "download heavy assets once to
   the volume, boot fast" pattern (#96). No base-image swap.
5. **Worker tuner (Phase A):** already implemented and in PR #120. It keys
   on the `"trt"` substring; `onnx-trt` contains it, so it remains correct
   with no change.

## Design

### CI build + public artifact (`.github/workflows/lc0-build.yml`, variant=trt)

1. Keep the existing `variant` input (cuda-fp16|trt) and the CUDA toolkit
   install step. Remove the previous, incorrect "apt install
   libnvinfer-dev" approach and the `lc0 --help` grep verify step.
2. Download a **pinned** Microsoft `onnxruntime-linux-x64-gpu-<ort_ver>.tgz`
   from `microsoft/onnxruntime/releases`; unpack to `$ORT` (a build-temp
   dir). The `ort_ver` is a workflow input with a default chosen from
   onnxruntime's CUDA/TensorRT compatibility table.
3. Clone lc0 at the pinned `release/0.32` tag. Build with lc0's own
   `./build.sh` passing:
   `-Donnx=true -Donnx_libdir=$ORT/lib -Donnx_include=$ORT/include
   -Ddefault_backend=onnx-trt -Dgtest=false`.
4. **Real verification** (replaces the `--help` grep): invoke the built
   binary so it actually constructs the `onnx-trt` backend (e.g.
   `lc0 benchmark --backend=onnx-trt --nodes=1` with a tiny test net).
   CI runners have no GPU, so the pass condition is: the binary
   *recognises and attempts* `onnx-trt` and fails only with a
   device/CUDA-absent error — NOT with "unknown backend onnx-trt" and NOT
   with an onnxruntime-missing/link error. The exact expected stderr
   substring is pinned during planning from observed output, and the step
   fails the job on any other outcome. This catches both "onnx backend not
   compiled" and "onnxruntime not linked".
5. **Package (public, license-clean):** stage the lc0 binary + the
   onnxruntime `.so` set into a tarball with `lib/` and
   `patchelf --set-rpath '$ORIGIN/lib'`. **Do not include any
   libnvinfer/TensorRT `.so`.** Produce `lc0-v<ver>-linux-trt.tar.gz` +
   `.sha256`.
6. **Publish:** attach to release `lc0-v<ver>` with `append_body: true`
   so successive variant runs (cuda-fp16, trt) accumulate rather than
   overwrite the release body/assets.
7. The `variant=cuda-fp16` build/package/publish path is preserved and
   unchanged in behaviour.

### RunPod provisioning (`runpod_start.sh`)

- `LC0_VARIANT` selector (default `cuda-fp16`; `trt` opt-in).
- For `trt`: download `lc0-v<ver>-linux-trt.tar.gz`, verify sha256, extract
  once into `/workspace/bin/lc0-trt/` (binary + bundled onnxruntime `lib/`),
  persisted on the volume (idempotent, like the existing cuda-fp16 binary).
- **Fetch TensorRT separately:** if `/workspace/trt/` is absent, download
  the NVIDIA TensorRT runtime package (pinned to the version onnxruntime-gpu
  was built against) directly from NVIDIA into `/workspace/trt/`. Idempotent,
  once per volume — same pattern as the Syzygy/weights downloads in
  `bootstrap.sh`.
- Export `LD_LIBRARY_PATH="/workspace/bin/lc0-trt/lib:/workspace/trt/lib:${LD_LIBRARY_PATH:-}"`
  so the bundled onnxruntime libs and the volume TensorRT libs both resolve.
- Set `WLW_LC0_PATH=/workspace/bin/lc0-trt/lc0`.

### RunPod runtime (`bootstrap.sh`)

- Variant-derived default: `export WLW_LC0_BACKEND="${WLW_LC0_BACKEND:-onnx-trt}"`
  when `LC0_VARIANT=trt`, else the existing `cuda-fp16` default.
- **Persist the TRT engine cache** on the volume: create
  `/workspace/data/trt-engine-cache` and export
  `ORT_TENSORRT_ENGINE_CACHE_ENABLE=1` and
  `ORT_TENSORRT_CACHE_PATH=/workspace/data/trt-engine-cache`. This makes the
  multi-minute TensorRT engine build happen once per (network, GPU) and be
  reused across pod stop/start and across serverless cold starts.
- Planning includes a discovery+verify task: confirm lc0's `onnx-trt`
  backend honours the `ORT_TENSORRT_*` environment variables; if it instead
  requires a lc0 backend sub-option string (e.g.
  `backend=onnx-trt(<opts>)`), wire that via
  `services/local_worker/local_worker/analysis/lc0.py::_build_engine_opts`
  instead. Done only when the L4 reuse check (below) passes.

### On-L4 verification (runbook — acceptance evidence)

1. Region/volume preflight: the L4 pod/endpoint must be created in the
   network volume's region (volumes are region-locked).
2. A/B: same fixed game (known PGN, 25k nodes) on `cuda-fp16` then on
   `onnx-trt`, against the same volume. Capture nps and per-game seconds
   from `/workspace/logs`. Post both to issue #119 (TRT measured, not
   assumed).
3. Persistence: across a stop/start on the trt pod, the second session log
   shows **no** MinibatchSize recalibration (tuning cache reused) **and**
   **no** TensorRT engine rebuild (`ORT_TENSORRT_CACHE_PATH` reused).

## Risks

- **Version matrix (primary risk):** the CUDA toolkit, the chosen
  onnxruntime-gpu release, and the NVIDIA TensorRT package must be a
  mutually compatible triple per onnxruntime's compatibility table, and
  compatible with the L4's driver. CI cannot exercise the GPU, so the
  authoritative gate is the on-L4 A/B step. Mitigation: pin all three as
  explicit CI inputs / script constants documented in one place; the L4
  smoke is a required acceptance step before declaring done.
- **CI verification fidelity:** step 4 only proves the binary is built
  correctly (backend recognised, onnxruntime linked), not that TRT runs —
  that is intentionally deferred to the L4 runbook. The pinned stderr
  assertion must be chosen carefully so it does not pass on a broken link.
- **TensorRT download source/stability:** NVIDIA's download URLs/auth can
  change; the provision-time fetch must fail loudly and idempotently and
  document the exact package. A failed TRT fetch must not corrupt the
  volume (atomic `.part` rename like the existing downloads).
- **Engine-cache option uncertainty:** if lc0's onnx-trt ignores the
  `ORT_TENSORRT_*` env vars, cold starts pay the multi-minute engine build
  every boot until the backend sub-option path is wired. Covered by the
  discovery+verify task; not a correctness risk, a performance one.
- **Bundled-onnxruntime size:** the public trt tarball is materially larger
  than cuda-fp16; acceptable because it is downloaded once per volume,
  consistent with the existing lc0/weights/Syzygy pattern.

## Acceptance

- CI `variant=trt` builds lc0 `release/0.32` (pinned tag) against a pinned
  Microsoft onnxruntime-gpu, the binary constructs the `onnx-trt` backend,
  and the public release tarball contains lc0 + onnxruntime libs and **no
  TensorRT libs**.
- `variant=cuda-fp16` continues to build/publish unchanged.
- A trt pod downloads the tarball + fetches TensorRT to the volume, runs
  lc0 on `onnx-trt`, and the TensorRT engine cache persists across
  stop/start (no rebuild on second boot).
- On an L4: measured `onnx-trt` vs `cuda-fp16` nps/per-game seconds are
  captured on issue #119.
- No NVIDIA TensorRT libraries are republished in any public artifact.
- The RunPod base image is unchanged; Phase A tuner (PR #120) needs no
  modification.
