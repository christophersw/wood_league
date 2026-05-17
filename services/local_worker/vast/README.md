# vast.ai Bulk Analysis Worker — Operator Runbook

Self-contained private image that runs the Wood League chess analysis
worker on vast.ai for bulk campaigns. 1 lc0 (GPU, TensorRT) and **N**
Stockfish (CPU) workers — N auto-derived from the host — run
**concurrently** in one instance against a shared WAL eval cache that is
pulled at boot and checkpointed back to object storage — no host-scoped
volume.

> Prerequisite: sub-project **E** (`--max-jobs` / `WLW_MAX_JOBS`) gives
> each engine a deterministic job-count stop. Until E ships, a run is
> bounded only by `WLW_BATCH_TIME` / queue-empty; the `WLW_MAX_JOBS`
> plumbing is already wired and activates automatically once E lands.

## One-time setup

1. **Private registry.** The image bakes the operator-supplied TensorRT
   tarball, so the registry MUST be private (GHCR private package or a
   Docker Hub private repo). Build/push is automated by
   `.github/workflows/build-vast-worker.yml`. The Syzygy 3-4-5
   tablebase is baked over **`http://`** (the `https://` mirror serves
   an empty listing and used to ship a tablebase-less image silently);
   the build now hard-fails if the listing is empty or the download
   count doesn't match (#129).
2. **vast.ai registry auth.** Configure pull credentials for the private
   registry on the vast.ai account.
3. **vast.ai SSH key.** `vastai create ssh-key` / `vastai attach ssh-key`
   so `--ssh` instances are reachable.
4. **Object storage.** A Railway (S3-compatible) bucket reachable via the
   env vars below.

## Launch a campaign

```bash
vastai create instance <offer-id> \
  --image <private-registry>/vast-worker:<tag> \
  --env '-e WLW_API_URL=<worker-api-url> -e WLW_API_KEY=<worker-token> \
         -e WLW_MAX_JOBS=<N> -e WL_CAMPAIGN_ID=<campaign-id> \
         -e RAILWAY_BUCKET_NAME=<bucket> -e ENDPOINT=<s3-endpoint> \
         -e REGION=<region> -e ACCESS_KEY_ID=<key> \
         -e SECRET_ACCESS_KEY=<secret> \
         [-e WL_SKIP_CACHE_PULL=1] [-e WL_CACHE_CHECKPOINT_MINUTES=<m>] \
         [-e WLW_BATCH_TIME=<minutes>] [-e WL_INSTANCE_ID=<id>]' \
  --onstart wlw-vast-onstart --ssh
```

> `WLW_API_URL` / `WLW_API_KEY` (and the bucket creds) are stable across
> campaigns. **Bake them into the vast Template's `env` field**
> (`vastai update template <hash> --env '-e WLW_API_URL=… …'`) — that is
> the *only* account-stored mechanism that actually reaches the
> container. Vast.ai account "env vars / secrets" do **not** auto-inject
> into instances (verified the hard way). Template `env` merges with the
> launch `--env`, so only per-run values (`WL_CAMPAIGN_ID`,
> `WLW_MAX_JOBS`) need `-e` at launch. Note: an interactive `ssh` session
> will *not* show these (SSH gets a fresh shell, not the entrypoint env);
> check `vastai logs`, not `env`, to confirm the worker got them.

### Micro batch (e.g. 20 jobs)

Identical recipe, just a small cap and a cheap/interruptible offer (API +
bucket creds assumed stored as vast account env vars):

```bash
vastai create instance <cheap-offer> \
  --image <private-registry>/vast-worker:<tag> \
  --env '-e WLW_MAX_JOBS=20 -e WL_CAMPAIGN_ID=micro-20260516' \
  --onstart wlw-vast-onstart --ssh
```

## Environment contract

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `WLW_API_URL` | **yes** | — | Wood League Worker API base URL. The worker is a pull client; without this both engines print `Not configured. Run \`wood-league-worker setup\` first.` and exit immediately. Supply as a vast account env var (auto-injects) or per-launch `-e`. |
| `WLW_API_KEY` | **yes** | — | Worker API token. Same failure mode as `WLW_API_URL` if absent. Treat as a secret — prefer a vast account env var over the command line. |
| `WL_CAMPAIGN_ID` | yes | — | Logical campaign; namespaces this instance's cache delta. |
| `WLW_MAX_JOBS` | no | unset | Per-engine job cap. Unset = drain until queue-empty / batch-time. With both engines a game ≈ 2 jobs (1 lc0 + 1 Stockfish). **Auto-fan-out:** this stays the *total* Stockfish cap; the entrypoint partitions it across the N Stockfish workers it spawns (e.g. cap 12 over 7 workers → `[2,2,2,2,2,1,1]`). You do **not** set Stockfish threads/workers/hash — they are derived from the host. |
| `WL_INSTANCE_ID` | no | `<hostname>-<pid>` | Stable per-instance id; the delta object key. Set explicitly to avoid collisions if you reuse a host. |
| `WL_SKIP_CACHE_PULL` | no | `0` | `1` skips the boot-time canonical pull (tiny / known-disjoint runs). |
| `WL_CACHE_CHECKPOINT_MINUTES` | no | `10` | Periodic cache snapshot+upload interval. |
| `WLW_BATCH_TIME` | no | `1440` | Safety ceiling in minutes (runaway protection on a billed GPU). |
| `RAILWAY_BUCKET_NAME` | yes | — | Object-storage bucket. |
| `ENDPOINT` | yes | — | S3-compatible endpoint URL. |
| `REGION` | no | `us-east-1` | Bucket region. |
| `ACCESS_KEY_ID` | yes | — | Bucket access key. |
| `SECRET_ACCESS_KEY` | yes | — | Bucket secret key. |

## Choosing an offer

1 lc0 + **N** Stockfish workers run at once (N is auto-derived from the
host at boot — see *Auto-fan-out* below), so filter offers on:

- **vCPUs:** more is better — every spare core becomes another Stockfish
  worker. The entrypoint reserves a few cores for lc0 + the OS and turns
  the rest into 4-thread Stockfish workers (capped for cache safety).
- **RAM:** lc0 + the BT4 network + Syzygy, plus ~0.75 GB per Stockfish
  worker. RAM can legitimately cap N below what the CPU count allows.
- **GPU:** an Ada-class card (the TensorRT backend's payoff target).

A crash of one engine does not strand the rest; the entrypoint waits for
**all** engine processes, then uploads the final cache delta.

### Auto-fan-out (no manual sizing)

At boot the entrypoint runs `wood-league-worker plan-sf-fanout`, which
reads the host vCPU + available RAM and prints the resolved
`SF_WORKERS` / `SF_THREADS` / `SF_HASH_MB` / `SF_JOB_SPLIT`. The
entrypoint then launches 1 lc0 + that many Stockfish workers. You no
longer set `WLW_STOCKFISH_THREADS` / `WLW_STOCKFISH_HASH_MB` / a worker
count — they are computed. The chosen values are echoed once near the
top of the log (`onstart: fan-out SF_WORKERS=… …`).

### Logs are per-engine

Each engine writes its **own** file under
`/root/.local/state/wood-league-worker/log/`:

- `lc0.log` — the single lc0 process (truncated each session).
- `stockfish.log` — **all N** Stockfish workers, appended to one shared
  file (record-atomic across processes).

`vastai logs <instance-id>` shows the boot/stdout TUI; for real
per-engine detail SSH in and `tail -f` the file above. The session-log
uploader ships *both* `lc0.log` and `stockfish.log` (no longer a single
`worker.log`).

## Stop the instance — it does NOT self-destroy

Unlike RunPod, a vast.ai **on-demand** instance keeps running (and
billing) after the entrypoint exits. When you see
`onstart: both engines exited; final delta uploaded; instance done` in
the logs the work is finished, but **you must destroy the instance
yourself** or it bills idle until the vast.ai instance is removed:

```bash
vastai destroy instance <instance-id> -y
```

`WLW_BATCH_TIME` only bounds the *worker*, not the instance — it does not
stop billing. (An interruptible/bid instance is reclaimed by vast, but an
on-demand one is not.) Watch the run with `vastai logs <instance-id>`;
destroy as soon as it reports done.

## Between campaigns — merge deltas into the canonical

Run **manually, server-side** (not on vast), once per campaign. Download
every per-instance delta under `eval_cache/checkpoints/<campaign-id>/`
from the bucket, then:

```bash
wood-league-worker cache-merge \
  --canonical canonical.sqlite \
  --delta inst-1.sqlite --delta inst-2.sqlite [--delta ...] \
  --max-mb 500
```

This unions the deltas into `canonical.sqlite` (last-writer-wins on the
`(zobrist, network, nodes, multipv)` key — safe because the engine is
deterministic at fixed nodes), prunes to `--max-mb`, and vacuums. Upload
the resulting `canonical.sqlite` back to the bucket as
`eval_cache/canonical.sqlite` — it becomes the next campaign's
boot-time-pull source. The canonical is intentionally one campaign behind.
