# vast.ai bulk analysis worker: baked image + boot-time-pull eval cache + bounded runs

- **Date:** 2026-05-15
- **Component:** `services/local_worker`, deployment/provisioning
- **Status:** Draft (brainstorming) — pending spec review
- **Scope:** Sub-projects **A+B** (run the existing pull worker on vast.ai for
  bulk analysis + a no-region-volume asset/cache strategy) **plus E**
  (`--max-jobs` run cap), pulled in from deferred as an in-scope prerequisite.
- **Deferred (separate specs):** C (vast.ai serverless on-ingest),
  D (vast.ai control-plane replacing the RunPod-API dispatch).

## Problem

Issue #119 proved the `onnx-trt` lc0 backend is worth shipping on
production-class Ada (+31.4% on an uncapped L40S). RunPod had no L40
available, forcing the A/B onto vast.ai, which surfaced that production
should move RunPod → vast.ai.

vast.ai breaks the RunPod model in one specific way: **volumes are strictly
host-scoped** — physically tied to the machine they were created on, no
cross-machine attach. RunPod's "one region volume, any pod reuses its
provisioned binaries/weights/caches" model is therefore unavailable. The
worker core is already platform-agnostic (an HTTP *pull* client,
`WorkerClient.checkout`, fed by `WLW_*` env); all RunPod-ness is in
provisioning/caching scripts. So this is a **provisioning and caching
problem, not a worker rewrite** — with one worker-loop change (E) folded in
to make bounded, self-terminating runs the default operating model.

## Goals

1. Run the existing pull worker on vast.ai for bulk analysis with **no
   region volume** and **no per-boot provisioning download** of binaries,
   weights, or tablebases.
2. Preserve and compound the engine evaluation cache across campaigns
   despite host-scoped volumes, without baking an ever-growing blob into
   every image.
3. Make every vast run **deterministically bounded and self-terminating**
   (works identically for a 10-game micro batch and a 100k-game campaign).
4. No correctness regression: the existing `eval_cache` and worker-loop
   test suites remain the backstop.

## Non-goals

- vast.ai serverless (sub-project C — separate spec; the existing
  `2026-05-15-runpod-serverless-on-ingest` spec is RunPod-coupled and must
  be redesigned for vast).
- A vast.ai control-plane / automated start-stop-dispatch (sub-project D).
  A+B launches via the manual, parameterized `vastai create` template.
- Re-designing the run cap. E's contract is fixed by the existing approved
  spec `2026-05-15-worker-max-jobs-run-cap-design.md`; this spec adopts it
  as-is and only wires it into the vast entrypoint.
- Any change to the analysis algorithms, job API, or `eval_cache` schema.

## Design

### Asset strategy: one baked private image

A single self-contained image, pushed to a **private registry** (GHCR or a
Docker Hub private repo — licensing-safe for the operator-supplied
TensorRT tarball; vast.ai supports private-registry auth):

| Baked in | Source | Approx size |
|---|---|---|
| CUDA + cuDNN9 runtime | `nvidia/cuda:*-cudnn-runtime` base image | 2–3 GB |
| lc0 (TRT build, portable CUDA arch) | #122/#123 build artefacts | a few MB |
| BT4 weights | build-time fetch | ~1 GB |
| Syzygy 3-4-5 WDL+DTZ | build-time fetch | ~1 GB |
| TensorRT libraries | operator tarball (`WLW_TRT_URL`), baked (private) | per tarball |
| `wood-league-worker` | PyPI, pinned version | small |
| lc0 calibration cache seed | `lc0_tuning.cache_path()` JSON | small |

`WLW_*` env points at the in-image paths for binary / weights / Syzygy.
The **eval cache is deliberately NOT baked** — it is pulled at boot (below)
so a growing, capped artefact never bloats CI builds or per-host image
pulls. Rationale: a fully baked image gives the fastest deterministic cold
boot for the heavy *stable* assets; the eval cache is the one asset that
grows and benefits from being decoupled.

### Run model: bounded, self-terminating (sub-project E, in scope)

This spec adopts the existing approved design
`2026-05-15-worker-max-jobs-run-cap-design.md` unchanged. Summary of the
parts this spec depends on:

- The worker loop is restructured to **claim exactly one job per
  checkout** (no multi-job reservation).
- New count cap `WLW_MAX_JOBS` / `--max-jobs` (blank/unset = drain until
  the queue is empty). Values `< 1` are treated as unset.
- `--batch-time` / `batch_time_minutes` is **kept as a coexisting safety
  ceiling** — on vast it is runaway protection for a billed GPU. Stop
  conditions are OR'd: queue-empty, count cap, time cap, or stop_event;
  first to fire ends the run.
- `--batch-size` / `WLW_DEFAULT_BATCH_SIZE` are removed (clean rename, no
  alias) per that spec; worker version bump and RunPod-script edits are
  owned by that spec's change set.

**Bounded run becomes the default operating model on vast.** Every
instance is "pull N jobs one-at-a-time, analyse, submit per job, exit."

**Games vs jobs:** the operator-facing knob is the worker's existing
`WLW_MAX_JOBS` (a *job* count), passed straight through by the entrypoint —
no separate "games" unit is introduced. With both engines enabled a game
produces ≈ 2 jobs (one lc0 + one Stockfish); this 2× relationship is
documented at the launch surface. (Open item O1 if a true games-unit knob
is later wanted.)

### Eval cache lifecycle

The cache is `eval_cache.py` — a single SQLite file (WAL mode) at
`<user-data-dir>/eval_cache.sqlite`, one row per
`(zobrist, network, nodes, multipv)`, ≈0.5–0.7 KB/row, self-capped by the
built-in `prune(max_bytes)` LRU eviction. Lifecycle:

**1. Boot-time-pull (fail-soft).** The `--onstart` entrypoint downloads the
canonical `eval_cache.sqlite` from the bucket (the project's Railway object
storage) to the worker's writable `<user-data-dir>` path, then starts the
worker. On a missing object, a failed fetch, or a corrupt file, the worker
starts with an empty cache and runs normally — this already matches the
corrupt-DB drop-and-recreate path in `EvalCache._init_schema`. The worker
never blocks on cache I/O. A `WL_SKIP_CACHE_PULL=1` env opt-out skips the
download entirely (for tiny or known-disjoint runs).

Economics (why pull is worth it for bulk): the download is a fixed
one-time cost (~2–40 s for a capped 0.2–1 GB file at ≥100 MB/s); each hit
skips the engine entirely (~0.05–1 s saved). Break-even ≈ 50–200 hits; a
bulk campaign yields thousands. The realized hit rate is observable via the
existing issue-#85 hit-rate sampling, so the bet is empirically verifiable,
not blind.

**2. Periodic + on-exit checkpoint export (no live merge).** A loop in the
entrypoint, every `WL_CACHE_CHECKPOINT_MINUTES` (default 10) **and** on
worker exit, uploads *this instance's own* cache to a per-instance key:
`checkpoints/<WL_CAMPAIGN_ID>/<instance-id>/eval_cache.sqlite`. It
overwrites only its own object — never reads other instances' caches, never
writes the canonical object at runtime. Robust to vast preemption: worst
case loses < one checkpoint interval of accumulated entries.

Because the worker holds the DB open in WAL mode, a live file copy is
unsafe; the checkpoint produces a consistent snapshot with
`VACUUM INTO <tmp>` (or the SQLite backup API) and uploads that.

The final export hangs off the worker's **normal exit path** (cap reached
or queue empty), so a bounded run always persists its delta without
operator action. A SIGTERM/SIGINT trap runs the same final export as
**preemption insurance** for interruptible instances reclaimed mid-run.

**3. Offline merge (server-side, manual, between campaigns).** Run
explicitly between campaigns — no cron, no live merge. The job downloads
all `checkpoints/<campaign-id>/*` deltas, opens the current canonical, and
replays each delta with `INSERT OR REPLACE` on the
`(zobrist, network, nodes, multipv)` primary key — last-writer-wins is
correct because the engine is deterministic at fixed nodes (identical
position → identical eval). It then applies `prune(max_bytes)` to enforce
the size cap, `VACUUM`s, and uploads the result as the new canonical.
v1-schema payloads are already treated as a miss by `_decode_payload`, so
schema drift is handled. The canonical is intentionally **one campaign
behind**; this is accepted.

### Launch surface (A+B)

The manual, parameterized `vastai create` template (a real control-plane
is sub-project D, deferred):

```
vastai create instance <offer-id> \
  --image <private-registry>/wood-league-worker:<tag> \
  --env '-e WLW_MAX_JOBS=<N> -e WL_CAMPAIGN_ID=<campaign-id> \
         -e <bucket-credentials> [-e WL_SKIP_CACHE_PULL=1] \
         [-e WL_CACHE_CHECKPOINT_MINUTES=<m>] -e WLW_<asset paths>' \
  --onstart <entrypoint> --ssh
```

vast SSH requires the account pubkey (`vastai create/attach ssh-key`); the
private registry requires vast registry credentials configured once.

## Components

| # | Component | Responsibility | Depends on |
|---|---|---|---|
| C1 | Baked private image (Dockerfile + build) | Ship all stable assets + worker | #119/#122/#123 build, private registry |
| C2 | `--onstart` entrypoint | pull cache → export `WLW_*` → start worker; SIGTERM trap; final export on exit | C3, C4 |
| C3 | Boot-time-pull (fail-soft) | Fetch canonical cache; degrade to empty | bucket creds |
| C4 | Checkpoint export | `VACUUM INTO` snapshot; periodic + on-exit upload to per-instance key | bucket creds |
| C5 | Offline merge job (server-side, manual) | Union deltas → prune → vacuum → publish canonical | bucket creds |
| E  | Worker run cap (existing spec, adopted) | One-at-a-time checkout; `WLW_MAX_JOBS`; clean exit | its own spec/PR |

## Data flow

```
build: assets + worker  ──▶  private image  ──▶  registry
boot:  pull canonical eval cache (fail-soft, unless WL_SKIP_CACHE_PULL)
       └▶ export WLW_*  └▶ start worker
run:   WorkerClient.checkout(count=1) loop
       └▶ analyse  └▶ eval_cache.get/put  └▶ submit per job
       every WL_CACHE_CHECKPOINT_MINUTES: VACUUM INTO snapshot ─▶ upload own delta
exit (max_jobs | queue empty | batch-time | SIGTERM):
       final VACUUM INTO snapshot ─▶ upload own delta ─▶ process exits
between campaigns (manual, server-side):
       download all deltas ─▶ INSERT OR REPLACE into canonical
       ─▶ prune(max_bytes) ─▶ VACUUM ─▶ publish new canonical
```

## Error handling

- **Cache pull fails / object missing / corrupt:** worker starts empty,
  continues; no run impact.
- **Checkpoint upload fails:** retried next interval; final export is
  best-effort; loss bounded by the checkpoint interval. The worker never
  blocks on cache I/O.
- **Instance preempted mid-run:** SIGTERM trap exports the partial delta;
  unexported work since the last checkpoint is lost (bounded, acceptable).
- **Merge job fails:** offline only — no runtime impact; the canonical
  simply is not advanced this cycle.
- **Bad/zero `WLW_MAX_JOBS`:** per E's spec, `< 1` is treated as unset
  (drain until queue empty); `--batch-time` ceiling still bounds the run.

## Testing

- **Unit:** `VACUUM INTO` produces a valid, openable DB while the source is
  WAL-active; merge union semantics (`INSERT OR REPLACE` last-writer-wins;
  v1 payloads treated as miss); `prune(max_bytes)` enforces the cap
  post-merge.
- **Integration:** boot-time-pull fail-soft (missing object → worker still
  runs and analyses); `WL_SKIP_CACHE_PULL` bypasses the download;
  end-to-end small campaign — two simulated instances each checkpoint a
  delta → manual merge → canonical row count grows → a fresh boot against
  the merged canonical yields hit-rate > 0.
- **Adopted from E's spec:** one-at-a-time checkout; warm lc0 engine
  launched once across N single-job claims; `WLW_MAX_JOBS` cap stops the
  run; blank = drain; count/time cap interaction.
- Existing `eval_cache` and `loop` suites remain the correctness backstop.

## Risks

- **Private-registry auth on vast:** a misconfigured credential fails the
  image pull on a headless instance. Mitigation: documented one-time
  `vastai` registry-auth setup; verify with a throwaway pull before a
  campaign.
- **Snapshot-while-WAL:** copying the live DB file instead of
  `VACUUM INTO` would upload a torn database. Mitigation: the snapshot step
  is `VACUUM INTO`/backup-API only; a unit test asserts validity under an
  open WAL connection.
- **Lost delta on hard destroy:** if an operator `vastai destroy`s before
  the final export completes, that instance's delta is lost. Mitigation:
  the bounded-run clean-exit export is the primary path (no manual stop
  needed); SIGTERM trap covers preemption; periodic checkpoints bound the
  loss for long runs.
- **E coupling:** this spec is inert until E's worker-loop change lands.
  Sequencing below makes E a prerequisite, not a parallel track.

## Acceptance

- A vast instance launched from the private image runs bulk analysis with
  zero per-boot provisioning download of binaries/weights/Syzygy.
- `WLW_MAX_JOBS=N` causes the instance to analyse N jobs and exit; the exit
  path uploads the instance's cache delta without operator action.
- A missing/failed canonical fetch does not prevent the run.
- After a manual merge of per-instance deltas, the canonical grows and a
  subsequent boot shows a non-zero cache hit rate.
- `--batch-time` still bounds a run as a safety ceiling.
- Micro batch (e.g. `WLW_MAX_JOBS=20`) and a large campaign use the
  identical launch recipe, differing only by `WLW_MAX_JOBS` and offer size.

## Open items

- **O1 — games-unit knob:** expose only `WLW_MAX_JOBS` (job count) for now;
  revisit if operators want to specify games and have the entrypoint
  translate via the enabled-engine multiplier.
- **O2 — checkpoint key collision on host reuse:** `<instance-id>` source
  (vast instance id vs generated UUID) to be pinned during planning so two
  runs on a reused host cannot overwrite each other's checkpoint object.
- **O3 — canonical bucket path/credentials:** exact Railway bucket name and
  credential delivery (env vs mounted) to be fixed in the implementation
  plan.

## Dependencies & sequencing

1. **E** (`2026-05-15-worker-max-jobs-run-cap-design.md`) lands first — the
   bounded clean-exit behaviour the cache export hangs off.
2. **C1** baked image (consumes #119/#122/#123 build outputs).
3. **C3/C4** cache pull + checkpoint export, then **C2** entrypoint wiring.
4. **C5** offline merge job.
5. End-to-end validation on a real vast instance.
