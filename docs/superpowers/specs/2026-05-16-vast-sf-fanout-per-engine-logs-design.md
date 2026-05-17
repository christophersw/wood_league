# Vast.ai worker: Stockfish auto-fan-out + per-engine logs + eval-cache concurrency

- **Date:** 2026-05-16
- **Issues:** closes #130 (auto-fan-out + per-engine logs + O4) and #129 (Syzygy https→http + build guard)
- **Status:** approved design → implementation plan next

## Context

The vast.ai dual-engine bulk worker was validated end-to-end (lc0 6/6,
0 errors, GPU 96%; Stockfish completing in parallel). Two gaps surfaced
from that run:

1. **CPU is massively under-used.** `onstart.sh` runs exactly **one**
   Stockfish process. `loop.py:227` passes `threads=settings.stockfish_threads`
   explicitly into `analyze_pgn`, which **overrides** the existing
   `auto_tune` path (`stockfish.py:348`); `stockfish.py:357` baselines
   `Threads=4`. Result: on a 32-vCPU L40S, Stockfish ran `Threads=4`,
   ~19% total CPU, ~26 cores idle behind the GPU-bound lc0. Large bulk
   throughput is left on the table every campaign.
2. **Logs are unreadable.** Both engine processes write one shared
   `worker.log`, interleaved — operators can't follow lc0 vs Stockfish.

Separately, the same image silently shipped with **no Syzygy
tablebases** (`Found 0 WDL … Failed to load Syzygy tablebases!`):
`vast/Dockerfile` pulls 3‑4‑5 over `https://tablebase.sesse.net`, which
does not serve them reliably; the empty `$(...)` list makes the build
exit 0 with an empty `/opt/syzygy` (issue #129).

These ship together as **one worker release** (operator decision).

## Goals

- Stockfish automatically uses the available CPU/RAM of whatever vast.ai
  offer it lands on — no per-campaign tuning.
- lc0 and Stockfish logs are separately readable.
- Concurrent Stockfish workers cannot corrupt or error on the shared
  eval cache.
- Syzygy tablebases are actually baked; an empty set fails the build.

## Non-goals (YAGNI)

- Dynamic re-balancing of fan-out at runtime (fixed at boot).
- Per-process Stockfish log files (decided: per-engine, 2 files).
- A combined `worker.log` compatibility shim.
- lc0 fan-out (GPU-bound — stays a single process).
- Rewriting the worker loop / checkout model (the validated
  one-at-a-time `--max-jobs` model is unchanged).

## Locked decisions

| Decision | Choice |
|---|---|
| SF sizing | **Auto-size to the box** (no operator knobs; a safety cap constant only) |
| Architecture | **Approach A**: `onstart.sh`-orchestrated fan-out + a pure sizing helper |
| #129/#130 | **Bundled**, one branch, one version bump, one image rebuild |
| O4 | **In scope** — prerequisite for safe auto-fan-out |
| Logs | **Per-engine, 2 files** (`lc0.log`, `stockfish.log`) |

## Architecture (Approach A)

**Components**

1. **`analysis/sf_fanout.py`** — new *pure* module. Input: host logical
   CPUs, available RAM MB, `WLW_MAX_JOBS` (optional). Output:
   `(sf_workers, sf_threads, sf_hash_mb, per_worker_max_jobs: list[int])`.
   No I/O; fully unit-testable. It owns **all** the math (fan-out *and*
   the job partition) so `onstart.sh` stays a thin spawn loop.
2. **`wood-league-worker plan-sf-fanout`** — tiny CLI wrapper that
   detects the host and prints the helper's result as shell-eval-able
   env (`SF_WORKERS=…`, `SF_THREADS=…`, `SF_HASH_MB=…`,
   `SF_JOBS_1=… SF_JOBS_2=…`).
3. **`onstart.sh`** — calls `plan-sf-fanout`, spawns **1 lc0** + **N
   Stockfish** `run` processes (each SF process gets its partitioned
   `--max-jobs`), `wait`s on all N+1, traps TERM/INT, runs the final
   cache push (otherwise unchanged).
4. **`eval_cache.py`** — O4 hardening (below).
5. **`logging_setup.py` / `log_upload.py`** — per-engine routing (below).

### Sizing heuristic (`sf_fanout`)

Named constants (module-level, easy to tune):

- `SF_THREADS_DEFAULT = 4` — Stockfish scales ~linearly to ~4–8; more
  parallel modest workers beats fewer fat ones for bulk throughput.
- `LC0_CPU_RESERVE = 3`, `OS_CPU_RESERVE = 1` — cores withheld from SF
  for the GPU-bound lc0 process and OS/worker overhead.
- `SF_HASH_MB_CAP = 512`; `SF_BASE_MB = 256` (per-SF non-hash RSS est.).
- `LC0_RAM_RESERVE_MB = 6144`, `OS_RAM_RESERVE_MB = 1024`.
- `SF_MAX_WORKERS = 16` — guardrail bounding eval-cache concurrent
  writers (auto, not an operator knob).
- Fallbacks: `cpu_count() or 1`; psutil-missing → assume
  `_FALLBACK_FREE_RAM_MB` (reuse `stockfish_tuning`'s constant/pattern).

Algorithm:

```
sf_threads = SF_THREADS_DEFAULT
usable_cpu = max(1, total_vcpu - LC0_CPU_RESERVE - OS_CPU_RESERVE)
cpu_workers = max(1, usable_cpu // sf_threads)

sf_hash_mb = SF_HASH_MB_CAP
ram_budget = max(0, avail_ram_mb - LC0_RAM_RESERVE_MB - OS_RAM_RESERVE_MB)
ram_workers = max(1, ram_budget // (sf_hash_mb + SF_BASE_MB))

sf_workers = min(cpu_workers, ram_workers, SF_MAX_WORKERS)
```

RAM is intentionally allowed to be the binding constraint on
high-CPU/low-RAM offers (`sf_workers` shrinks to fit).

### `WLW_MAX_JOBS` semantics (preserve operator mental model)

`WLW_MAX_JOBS` remains the **per-engine total**.

- lc0: single process → `--max-jobs WLW_MAX_JOBS`.
- Stockfish: `WLW_MAX_JOBS` is **partitioned across the N SF workers**
  (Σ per-worker caps = `WLW_MAX_JOBS`; remainder distributed to the
  first workers).
- If `WLW_MAX_JOBS < sf_workers`: spawn only `WLW_MAX_JOBS` SF workers,
  1 job each (no idle workers).
- `WLW_MAX_JOBS` unset: every SF worker drains until queue-empty /
  batch-time (no `--max-jobs` passed); `sf_workers` still applies.

The partition list is computed in `sf_fanout` (testable), not in bash.

## O4 — eval-cache concurrent-writer safety (`eval_cache.py`)

Current hazards: `sqlite3.connect` sets no `busy_timeout`; `get()`
itself writes (`UPDATE last_used_at`); the corrupt-DB path `unlink()`s a
file other processes may hold open.

1. **`PRAGMA busy_timeout` (5000 ms)** on every connection — concurrent
   writers wait for the lock instead of raising. Sufficient: cache
   writes are tiny vs. per-position analysis time.
2. **Best-effort degrade.** Wrap the `get()` `last_used_at` UPDATE and
   `put()` in a bounded retry; on residual
   `OperationalError: database is locked`, **skip the write, debug-log,
   continue**. The cache is an optimization — a contended write must
   never fail a job. (A failed `get()` read also degrades to a miss.)
3. **Remove the multi-process footgun.** Replace
   "corrupt → `unlink()` + recreate" with "corrupt → **disable this
   process's cache** (`enabled=False`, `log.warning`)". Never destroy a
   shared file other processes hold. True corruption is an offline
   concern — the canonical is already rebuilt server-side between
   campaigns.
4. Keep WAL + `synchronous=NORMAL` (already correct). **Verify**
   `cache_sync` snapshots the DB WAL-safely for the periodic delta push
   (e.g. sqlite backup API / safe copy); fix only if it does a naive
   file copy (check, not a redesign).

## Per-engine logging (2 files)

- `run --engine {lc0|stockfish}` already knows its engine; pass it into
  `logging_setup` so the file sink is `…/log/lc0.log` or
  `…/log/stockfish.log`.
- All N SF processes append the **same `stockfish.log`**. The live logs
  show the worker uses loguru — configure that sink with
  `enqueue=True` so multi-process appends are record-atomic. (Plan step:
  confirm `logging_setup`'s sink library; if not loguru, use its
  equivalent record-atomic multi-process append mechanism.)
- `log_upload.py` / `--telemetry`: upload **both** known files
  (`lc0.log`, `stockfish.log`) as per-engine `WorkerLog`s instead of the
  single `worker.log`. No combined log retained.
- Document the path change in the vast README + wiki (also unblocks the
  #128 dashboard work later).

## #129 — Syzygy (mechanical, same release)

- `vast/Dockerfile`: Syzygy 3‑4‑5 download `https://` → `http://` for
  `tablebase.sesse.net` (both the directory-listing curl and the
  per-file curl).
- After the loop, a build-time guard (same pattern as the existing
  `libnvinfer.so.10` guard): capture the count of `.rtbw`/`.rtbz` names
  parsed from the directory index, and fail the build unless that count
  is **> 0** *and* the number of files actually present in
  `/opt/syzygy` **equals** it (downloaded == listed). This catches both
  "listing failed → 0" and "partial download". Empty/partial Syzygy can
  never ship silently again.
- Cross-check `runpod/bootstrap.sh` for the same https issue; fix if
  present.

## Testing

- **`sf_fanout` (primary surface, pure):** parametrized table of
  `(vcpu, avail_ram_mb, WLW_MAX_JOBS)` → expected
  `(workers, threads, hash, job_partition)`. Edges: tiny box → 1 worker;
  RAM-bound → workers reduced; `≥ SF_MAX_WORKERS` → clamped;
  `WLW_MAX_JOBS < N`; `WLW_MAX_JOBS` unset; `cpu_count() is None`;
  psutil missing.
- **`EvalCache` O4:** K concurrent workers (threads/processes) hammer
  `get`/`put` on one DB → no exceptions; contended write is skipped not
  raised; corrupt DB → `enabled=False` and the file is **never**
  unlinked (assert inode/file survives).
- **Logging:** `logging_setup` routes lc0→`lc0.log`,
  stockfish→`stockfish.log`; SF sink configured with `enqueue=True`;
  `log_upload` enumerates and ships both.
- **Quality gate** (project standard): ruff → bandit+semgrep →
  radon/xenon → mypy → pytest+cov, run in the worker `.venv`.
- **One live L40S validation:** N SF workers spawn; `lc0.log` &
  `stockfish.log` separate; multiple SF workers + lc0 process games; no
  `database is locked`; Syzygy loads (`Found N>0 …`); cache delta
  uploads. Then **destroy the instance** (vast on-demand never
  self-stops).

## Release / workspace

- Worktree (superpowers:using-git-worktrees) at implementation time;
  branch `issue/130-vast-sf-fanout-per-engine-logs` off `main`; PR
  closes **#129 + #130**.
- One version bump: `pyproject.toml` `0.9.11 → 0.9.12`, and the
  `WORKER_VERSION` defaults in `vast/Dockerfile` &
  `.github/workflows/build-vast-worker.yml` → `0.9.12` (kill the
  recurring stale-default).
- Proven chain: commit → push → tag `worker-v0.9.12` (PyPI) → green →
  tag `vast-worker-v0.9.12` (image rebuild, includes #129) → live
  validate → destroy.
- Update vast README + wiki runbook (plain tone, cross-linked):
  per-engine log paths, auto-fan-out behavior, Syzygy fix.

## Risks / mitigations

- **Eval-cache write contention at high N** — bounded by
  `SF_MAX_WORKERS` + `busy_timeout` + best-effort degrade; cache is an
  optimization, never load-bearing.
- **RAM oversubscription on fat-CPU/thin-RAM offers** — RAM is the
  binding constraint in the heuristic; `sf_workers` shrinks to fit.
- **lc0 CPU starvation** — `LC0_CPU_RESERVE` withholds cores from SF.
- **Reserve constants are estimates** — exposed as named module
  constants; the single live validation confirms real headroom and they
  can be tuned in a fast follow if needed.
