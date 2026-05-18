# lc0 cold-start: eliminate the per-instance calibration sweep

- **Issue:** #150
- **Date:** 2026-05-17
- **Status:** Approved (design) — pending implementation plan

## Problem

Every fresh vast.ai instance pays the full **~7.5-minute** lc0 `benchmark`
MinibatchSize sweep before it can analyse a single game. The sweep itself is
not the bug — `lc0_tuning.py` already caches its result and only sweeps on a
cache miss. The bug is durability: the cache (`lc0_tuning.json`) is written
to the instance's **ephemeral data dir**, which is destroyed on teardown, so
every new box starts cold → miss → full sweep.

The "do the work ahead / reload state" mechanism is therefore already built.
It just doesn't survive instance teardown. This spec makes it survive.

## The pivotal constraint (verified in code)

`lc0_tuning.json` is a **single-entry flat dict for exactly one GPU**:

```json
{
  "fingerprint": {"gpu": "...", "lc0_version": "...", "weights": "<basename>", "backend": "..."},
  "minibatch_size": 256,
  "max_prefetch": 32,
  "measured_nps": 40450.0,
  "calibrated_at": "2026-05-17T..Z"
}
```

`get_tuned_opts()` returns the cached tuning **only when
`cache["fingerprint"] == fingerprint` exactly**, where the fingerprint is
`compute_fingerprint(gpu_name, lc0_version, weights_path, backend)`.

Two consequences drive the whole design:

1. **The fingerprint's `weights` field is the basename only**
   (`Path(weights_path).name`). The absolute weights path differing between
   the build/calibration host and a running instance does **not** cause a
   miss. Baking a pre-computed JSON into the image is safe.
2. **A single shared bucket object would clobber across GPU classes.**
   Because the on-disk cache holds exactly one GPU's entry, if boot
   pulled/pushed one canonical `lc0_tuning.json`, an L40S campaign would
   overwrite the L4 entry (and vice-versa) and every other GPU class would
   keep missing. The bucket object must be **keyed per fingerprint**.

## Goals

- A standard-rig (L40S) instance starts with a calibration **cache hit**:
  ~7.5 min → ~0.
- Any GPU class self-heals after its first-ever calibration: subsequent
  instances of that class hit.
- No regression for an un-cached GPU: it does exactly what it does today
  (correct full sweep).
- Minimal, isolated change to `lc0_tuning.py`; all object-storage I/O lives
  in a new sync module + the vast entrypoint (preserve `lc0_tuning.py`'s
  no-Django / no-I/O-in-decision-path testability).

## Non-goals (YAGNI)

- **Phase 3 — persisting lc0's own TensorRT engine plan cache.** Evidence
  shows the TRT plan compile is paid *inside* the sweep today, so killing
  the sweep removes the bulk. Revisit only if Phase 1+2 leave a noticeable
  startup tail.
- No change to the calibration algorithm, sweep tables, or fingerprint
  composition.

## Phase 1 — bake a known-good L40S cache into the image

- Commit `services/local_worker/vast/lc0_tuning.l40s.json` — the calibration
  result for the standard L40S rig, with the correct fingerprint (L40S GPU
  name string, current lc0 version, weights basename, the TRT backend in
  production use).
- `services/local_worker/vast/Dockerfile`: `COPY` it to the runtime
  `data_dir()/lc0_tuning.json` path. Fresh standard-rig instance → immediate
  hit → ~0 calibration. Other GPU/version → fingerprint mismatch → correct
  full sweep (no regression).
- **Build-time guard** (mirrors the #138 `WORKER_VERSION` guard philosophy):
  the Dockerfile asserts the baked JSON exists and its `fingerprint.gpu`,
  `fingerprint.lc0_version`, `fingerprint.backend` are non-empty — fail the
  build loud rather than silently bake a malformed/empty cache.
- **Capture method: piggyback (decided).** The worker already writes
  `lc0_tuning.json` after its first calibration. The next sea-trial pulls
  that file off the instance before teardown; we commit it verbatim. **Zero
  extra spend.** Phase 1 lands after the next trial.

### Phase 1 open item to pin during implementation

- Confirm the exact runtime value of `data_dir()` so the Dockerfile `COPY`
  target is exact (the bake is worthless if it lands off the path
  `cache_path()` reads).

## Phase 2 — bucket persistence (GPU-agnostic, self-healing)

New module `services/local_worker/local_worker/lc0_tuning_sync.py`, same
shape and fail-soft contract as `cache_sync.py` (never raises; any
error logs a warning and the worker proceeds exactly as today):

- `tuning_object_key(fingerprint: dict) -> str`
  → `lc0_tuning/<sha1(canonical-json(fingerprint))>.json`.
  One object per GPU/version/backend; deterministic; no cross-GPU clobber.
- `pull_tuning(client, bucket, fingerprint, dest) -> bool`
  Boot-time: derive the key from the **current host's** fingerprint,
  fail-soft `download_file` to `cache_path()`. Miss/error → log, return
  False, worker calibrates normally. Mirrors `pull_canonical`.
- `push_tuning(client, bucket, cache_path) -> None`
  After a fresh calibration: read the just-written `lc0_tuning.json`,
  derive the key from **its embedded** `fingerprint`, `upload_file`.
  Fail-soft.

### Integration points (both already exist)

1. **`lc0_tuning.py` change is a single optional callback.**
   Add `on_calibrated: Optional[Callable[[Path], None]] = None` to
   `get_tuned_opts()`; after the existing `save_cache(...)` on a cache
   miss, call `on_calibrated(cache_path)` if provided. Default `None` →
   no-op → unit behaviour unchanged, no S3, no Django imported. This is
   the *only* edit to `lc0_tuning.py`.
2. **The vast entrypoint owns all S3 wiring:**
   - At boot, after building the host fingerprint, call `pull_tuning(...)`
     (alongside the existing eval-cache `pull_canonical` call).
   - Wire `on_calibrated = lambda p: push_tuning(client, bucket, p)` into
     the `get_tuned_opts` call path so a fresh calibration is pushed once.

### Self-healing

A fingerprint change (new lc0 version, new weights file, different backend)
→ new object key → boot pull misses → worker recalibrates → push under the
new key. Stale keys orphan harmlessly (small JSON objects; optional future
lifecycle policy, out of scope here).

## Testing

Pure-unit, no live S3 / no Django (mirror `tests/test_cache_sync.py`):

- `tuning_object_key`: stable for identical fingerprint; differs when **any**
  fingerprint field differs; output is a valid object key.
- `pull_tuning`: success path writes `dest`; missing-object / raising client
  → returns False, no exception, partial file removed.
- `push_tuning`: reads the embedded fingerprint to form the key; raising
  client → no exception.
- `get_tuned_opts`: `on_calibrated` fires **exactly once** with the cache
  path on a cache **miss**, and **not at all** on a cache **hit**; default
  `None` path unchanged (regression guard for the single `lc0_tuning.py`
  edit).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Baked JSON lands off the real `data_dir()` path → silent no-op | Pin `data_dir()` value; Dockerfile build-time existence + non-empty-fingerprint assertion |
| Bucket object clobber across GPU classes | Per-fingerprint object key (core design decision) |
| S3 failure stalls/booms a campaign | Fail-soft contract inherited from `cache_sync` — never raises; worker proceeds with normal calibration |
| `lc0_tuning.py` edit regresses unit behaviour | Callback defaults to `None`; explicit regression test for the default path |
| Stale L40S bake after an lc0/weights bump | Fingerprint mismatch → correct full-sweep fallback + Phase 2 re-push under new key |

## Rollout / sequencing

- **Phase 1 first** (fast, near-zero risk, biggest single win for the
  standard rig). Lands opportunistically after the next sea-trial supplies
  the L40S JSON.
- **Phase 2 next** (the durable, GPU-agnostic mechanism + safety net).
- Worker package change → bump `services/local_worker/pyproject.toml` and
  follow the `vast-worker-v*` tag release flow before the new image is used
  in a paid campaign.
- **Phase 3 deferred** unless a measurable startup tail remains.
