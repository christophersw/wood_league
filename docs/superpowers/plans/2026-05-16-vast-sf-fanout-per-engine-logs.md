# Vast SF auto-fan-out + per-engine logs + eval-cache O4 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the vast.ai Stockfish worker auto-fan-out to the host's CPU/RAM, give lc0 and Stockfish separate log files, make the shared eval cache safe under concurrent SF writers, and fix the Syzygy download — shipped as one `0.9.12` worker release.

**Architecture:** A new *pure* `sf_fanout` module computes `(workers, threads, hash_mb, per-worker job split)` from host vCPU/RAM + `WLW_MAX_JOBS`; a `plan-sf-fanout` CLI command exposes it; `onstart.sh` consumes it and spawns 1 lc0 + N Stockfish `run` processes, passing per-worker values through the **existing** `WLW_STOCKFISH_THREADS` / `WLW_STOCKFISH_HASH_MB` / `WLW_MAX_JOBS` env→Settings overrides (so `loop.py`/`stockfish.py` are untouched). `eval_cache.py` gets `busy_timeout` + best-effort degrade + no-unlink. Logging is routed per engine. `#129` (Syzygy `https`→`http` + build guard) rides along.

**Tech Stack:** Python 3.11, Typer CLI, loguru, sqlite3 (WAL), pytest, bash (`onstart.sh`), Docker, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-05-16-vast-sf-fanout-per-engine-logs-design.md` (commit `1b01950`).

**Branch:** `issue/130-vast-sf-fanout-per-engine-logs` (already created off `main`; PR closes #129 + #130).

---

## Pre-flight (every session, before any task)

- [ ] `cd /Users/christopherwebster/Projects/wood_league`
- [ ] `git checkout issue/130-vast-sf-fanout-per-engine-logs` (the spec commit `1b01950` is here)
- [ ] `source services/local_worker/.venv/bin/activate` — **all** pytest/bandit/python run from the worker venv. If missing: `python3 -m venv services/local_worker/.venv && services/local_worker/.venv/bin/pip install -e 'services/local_worker[dev]'`
- [ ] Quick sanity: `cd services/local_worker && python -m pytest -q tests/ -x 2>&1 | tail -5` (baseline green), then `cd /Users/christopherwebster/Projects/wood_league`

Worker test dir: `services/local_worker/tests/`. Run tests with cwd `services/local_worker` (so `pytest tests/...`).

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `services/local_worker/local_worker/analysis/sf_fanout.py` | Pure host→fan-out math (workers/threads/hash/job-split) | **Create** |
| `services/local_worker/tests/test_sf_fanout.py` | Unit tests for the helper | **Create** |
| `services/local_worker/local_worker/commands/plan_sf_fanout_cmd.py` | `plan-sf-fanout` CLI (host detect → eval-able env) | **Create** |
| `services/local_worker/local_worker/cli.py` | Register the new subcommand | Modify |
| `services/local_worker/tests/test_plan_sf_fanout_cmd.py` | CLI output test | **Create** |
| `services/local_worker/local_worker/analysis/eval_cache.py` | O4: busy_timeout + degrade + no-unlink | Modify |
| `services/local_worker/tests/test_eval_cache_concurrency.py` | Concurrent-writer + corrupt-no-unlink test | **Create** |
| `services/local_worker/local_worker/logging_setup.py` | Per-engine log file (basename + append/enqueue) | Modify |
| `services/local_worker/tests/test_logging_per_engine.py` | Routing test | **Create** |
| `services/local_worker/local_worker/log_upload.py` | Upload both engine logs | Modify |
| `services/local_worker/vast/onstart.sh` | Fan-out spawn (1 lc0 + N SF), per-engine env, wait/trap | Modify |
| `services/local_worker/vast/Dockerfile` | #129 Syzygy http + guard; `WORKER_VERSION` 0.9.12 | Modify |
| `services/local_worker/runpod/bootstrap.sh` | #129 cross-check (https→http if present) | Modify (conditional) |
| `services/local_worker/pyproject.toml` | version 0.9.11 → 0.9.12 | Modify |
| `.github/workflows/build-vast-worker.yml` | `WORKER_VERSION` default → 0.9.12 | Modify |
| `services/local_worker/vast/README.md` + wiki | Per-engine log paths, fan-out, Syzygy fix | Modify (Task 9) |

---

## Task 1: `sf_fanout` pure sizing helper

**Files:**
- Create: `services/local_worker/local_worker/analysis/sf_fanout.py`
- Test: `services/local_worker/tests/test_sf_fanout.py`

- [ ] **Step 1: Write the failing test**

Create `services/local_worker/tests/test_sf_fanout.py`:

```python
"""Tests for the pure Stockfish fan-out sizing helper."""
from local_worker.analysis.sf_fanout import FanoutPlan, plan_fanout


def test_big_box_cpu_bound():
    # 32 vCPU, 120 GB RAM, cap 12. usable=32-3-1=28; 28//4=7 workers.
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=12)
    assert isinstance(p, FanoutPlan)
    assert p.workers == 7
    assert p.threads == 4
    assert p.hash_mb == 512
    assert sum(p.job_split) == 12
    assert len(p.job_split) == 7
    # 12 over 7 → [2,2,2,2,2,1,1]
    assert p.job_split == [2, 2, 2, 2, 2, 1, 1]


def test_ram_bound_reduces_workers():
    # 64 vCPU but only 4 GB RAM. cpu=64-4=60//4=15.
    # ram_budget = 4096-6144-1024 < 0 → max(0,...) → ram_workers=1.
    p = plan_fanout(vcpu=64, avail_ram_mb=4096, max_jobs=None)
    assert p.workers == 1
    assert p.job_split == []  # unbounded (max_jobs None)


def test_safety_cap_clamps():
    p = plan_fanout(vcpu=512, avail_ram_mb=1_000_000, max_jobs=None)
    assert p.workers == 16  # SF_MAX_WORKERS


def test_tiny_box_one_worker():
    p = plan_fanout(vcpu=1, avail_ram_mb=2048, max_jobs=None)
    assert p.workers == 1
    assert p.threads == 4


def test_max_jobs_less_than_workers_spawns_fewer():
    # cap 3 but box fits 7 → only 3 workers, 1 job each.
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=3)
    assert p.workers == 3
    assert p.job_split == [1, 1, 1]


def test_max_jobs_unset_no_split():
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=None)
    assert p.job_split == []


def test_none_cpu_count_falls_back_to_one():
    p = plan_fanout(vcpu=None, avail_ram_mb=120_000, max_jobs=None)
    assert p.workers == 1
```

- [ ] **Step 2: Run test, verify it fails**

Run (cwd `services/local_worker`): `python -m pytest tests/test_sf_fanout.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'local_worker.analysis.sf_fanout'`

- [ ] **Step 3: Implement the helper**

Create `services/local_worker/local_worker/analysis/sf_fanout.py`:

```python
"""
Title: sf_fanout.py — Pure host→Stockfish fan-out sizing
Description:
    Given the host's logical CPU count, available RAM, and the optional
    per-engine WLW_MAX_JOBS cap, compute how many concurrent Stockfish
    worker processes to run, the per-process Threads/Hash, and how to
    partition the job cap across them. Pure (no I/O) so it is fully
    unit-testable; the host probing lives in the plan-sf-fanout command.

    Heuristic (see 2026-05-16 spec): Stockfish scales ~linearly to ~4-8
    threads, so many modest workers beat few fat ones for bulk
    throughput. CPU and RAM are both budgeted; RAM is allowed to be the
    binding constraint. A safety cap bounds eval-cache concurrent
    writers.
Changelog:
    2026-05-16: Initial creation (#130).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SF_THREADS_DEFAULT = 4
LC0_CPU_RESERVE = 3
OS_CPU_RESERVE = 1
SF_HASH_MB_CAP = 512
SF_BASE_MB = 256
LC0_RAM_RESERVE_MB = 6144
OS_RAM_RESERVE_MB = 1024
SF_MAX_WORKERS = 16


@dataclass(frozen=True)
class FanoutPlan:
    """Resolved Stockfish fan-out for this host.

    Attributes:
        workers: Number of concurrent Stockfish worker processes.
        threads: Stockfish ``Threads`` per worker.
        hash_mb: Stockfish ``Hash`` (MB) per worker.
        job_split: Per-worker ``--max-jobs`` values; empty list means
            unbounded (no WLW_MAX_JOBS cap). ``sum`` == the cap;
            ``len`` == workers.
    """

    workers: int
    threads: int
    hash_mb: int
    job_split: list[int]


def _split_jobs(total: int, workers: int) -> list[int]:
    """Partition ``total`` jobs across ``workers`` as evenly as possible.

    Remainder goes to the first workers. ``len`` == workers, ``sum`` ==
    total.
    """
    base, rem = divmod(total, workers)
    return [base + (1 if i < rem else 0) for i in range(workers)]


def plan_fanout(
    *,
    vcpu: Optional[int],
    avail_ram_mb: int,
    max_jobs: Optional[int],
) -> FanoutPlan:
    """Compute the Stockfish fan-out for the current host.

    Args:
        vcpu: Host logical CPU count (``os.cpu_count()``); None → treat
            as 1.
        avail_ram_mb: Currently-available RAM in MB.
        max_jobs: Per-engine WLW_MAX_JOBS cap, or None for unbounded.

    Returns:
        A :class:`FanoutPlan`.
    """
    cpus = vcpu if (vcpu and vcpu > 0) else 1
    threads = SF_THREADS_DEFAULT

    usable_cpu = max(1, cpus - LC0_CPU_RESERVE - OS_CPU_RESERVE)
    cpu_workers = max(1, usable_cpu // threads)

    hash_mb = SF_HASH_MB_CAP
    ram_budget = max(0, avail_ram_mb - LC0_RAM_RESERVE_MB - OS_RAM_RESERVE_MB)
    ram_workers = max(1, ram_budget // (hash_mb + SF_BASE_MB))

    workers = min(cpu_workers, ram_workers, SF_MAX_WORKERS)

    if max_jobs is not None and max_jobs >= 1:
        if max_jobs < workers:
            workers = max_jobs
        job_split = _split_jobs(max_jobs, workers)
    else:
        job_split = []

    return FanoutPlan(
        workers=workers,
        threads=threads,
        hash_mb=hash_mb,
        job_split=job_split,
    )
```

- [ ] **Step 4: Run test, verify it passes**

Run: `python -m pytest tests/test_sf_fanout.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/sf_fanout.py
git add services/local_worker/local_worker/analysis/sf_fanout.py services/local_worker/tests/test_sf_fanout.py
git commit -m "feat(worker): pure sf_fanout host->fan-out sizing helper (#130)"
```

Expected bandit: `No issues identified.`

---

## Task 2: `plan-sf-fanout` CLI command

**Files:**
- Create: `services/local_worker/local_worker/commands/plan_sf_fanout_cmd.py`
- Modify: `services/local_worker/local_worker/cli.py` (register subcommand — see Step 3)
- Test: `services/local_worker/tests/test_plan_sf_fanout_cmd.py`

- [ ] **Step 1: Write the failing test**

Create `services/local_worker/tests/test_plan_sf_fanout_cmd.py`:

```python
"""plan-sf-fanout emits shell-eval-able env from the fan-out plan."""
from typer.testing import CliRunner

from local_worker.cli import app

runner = CliRunner()


def test_emits_eval_env(monkeypatch):
    # Force a deterministic host: patch the detectors used by the cmd.
    import local_worker.commands.plan_sf_fanout_cmd as m
    monkeypatch.setattr(m, "_host_vcpu", lambda: 32)
    monkeypatch.setattr(m, "_host_avail_ram_mb", lambda: 120_000)
    monkeypatch.setenv("WLW_MAX_JOBS", "12")

    result = runner.invoke(app, ["plan-sf-fanout"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "SF_WORKERS=7" in out
    assert "SF_THREADS=4" in out
    assert "SF_HASH_MB=512" in out
    # space-separated per-worker job caps
    assert "SF_JOB_SPLIT='2 2 2 2 2 1 1'" in out


def test_unbounded_emits_empty_split(monkeypatch):
    import local_worker.commands.plan_sf_fanout_cmd as m
    monkeypatch.setattr(m, "_host_vcpu", lambda: 8)
    monkeypatch.setattr(m, "_host_avail_ram_mb", lambda: 64_000)
    monkeypatch.delenv("WLW_MAX_JOBS", raising=False)

    result = runner.invoke(app, ["plan-sf-fanout"])
    assert result.exit_code == 0, result.output
    assert "SF_JOB_SPLIT=''" in result.output
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_plan_sf_fanout_cmd.py -q`
Expected: FAIL — command `plan-sf-fanout` not registered (`Error: No such command`).

- [ ] **Step 3: Implement command + register it**

Create `services/local_worker/local_worker/commands/plan_sf_fanout_cmd.py`:

```python
"""
Title: plan_sf_fanout_cmd.py — `plan-sf-fanout` CLI command
Description:
    Detects host vCPU + available RAM, reads the optional WLW_MAX_JOBS
    cap, runs the pure sf_fanout planner, and prints shell-eval-able
    env lines for onstart.sh:

        SF_WORKERS=<n>
        SF_THREADS=<t>
        SF_HASH_MB=<mb>
        SF_JOB_SPLIT='<space-separated per-worker caps, empty=unbounded>'

Changelog:
    2026-05-16: Initial creation (#130).
"""
from __future__ import annotations

import os

import typer

from local_worker.analysis.sf_fanout import plan_fanout


def _host_vcpu() -> int | None:
    """Host logical CPU count (``os.cpu_count()``)."""
    return os.cpu_count()


def _host_avail_ram_mb() -> int:
    """Currently-available RAM in MB; conservative 1024 if psutil absent."""
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        return 1024
    return int(psutil.virtual_memory().available // (1024 * 1024))


def _read_max_jobs() -> int | None:
    raw = os.environ.get("WLW_MAX_JOBS", "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed >= 1 else None


def plan_sf_fanout() -> None:
    """Print the resolved Stockfish fan-out as eval-able shell env."""
    plan = plan_fanout(
        vcpu=_host_vcpu(),
        avail_ram_mb=_host_avail_ram_mb(),
        max_jobs=_read_max_jobs(),
    )
    split = " ".join(str(n) for n in plan.job_split)
    typer.echo(f"SF_WORKERS={plan.workers}")
    typer.echo(f"SF_THREADS={plan.threads}")
    typer.echo(f"SF_HASH_MB={plan.hash_mb}")
    typer.echo(f"SF_JOB_SPLIT='{split}'")
```

Modify `services/local_worker/local_worker/cli.py` — add the import near the other command imports and register it with the other `app.command(...)` lines. Find the block (currently):

```python
app.command("submit-log")(submit_log_cmd.submit_log)
app.command("cache-merge")(cache_merge_cmd.cache_merge)
```

Add the import with the sibling command imports (near `from local_worker.commands import ...` / the existing `*_cmd` imports — match the existing import style in that file) :

```python
from local_worker.commands import plan_sf_fanout_cmd
```

and add, immediately after the `cache-merge` registration line:

```python
app.command("plan-sf-fanout")(plan_sf_fanout_cmd.plan_sf_fanout)
```

> Note: `plan-sf-fanout` is **not** long-running; do not add it to `LONG_RUNNING_COMMANDS`. The `_startup` callback will attach the read-only diagnostics sink, which is harmless — the command's stdout (the `SF_*` lines) is what `onstart.sh` consumes.

- [ ] **Step 4: Run test, verify it passes**

Run: `python -m pytest tests/test_plan_sf_fanout_cmd.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/commands/plan_sf_fanout_cmd.py
git add services/local_worker/local_worker/commands/plan_sf_fanout_cmd.py services/local_worker/local_worker/cli.py services/local_worker/tests/test_plan_sf_fanout_cmd.py
git commit -m "feat(worker): plan-sf-fanout CLI emits eval-able fan-out env (#130)"
```

---

## Task 3: eval-cache O4 — busy_timeout + best-effort degrade + no-unlink

**Files:**
- Modify: `services/local_worker/local_worker/analysis/eval_cache.py`
- Test: `services/local_worker/tests/test_eval_cache_concurrency.py`

Current behaviour (read the file first): `__init__` does `sqlite3.connect(str(db_path))` with **no** busy_timeout; `_init_schema` on `sqlite3.DatabaseError` does `self.db_path.unlink(missing_ok=True)` then recreates; `get()` issues an `UPDATE eval_cache SET last_used_at=...` + `commit()`; `put()` does `INSERT OR REPLACE` + `commit()`.

- [ ] **Step 1: Write the failing test**

Create `services/local_worker/tests/test_eval_cache_concurrency.py`:

```python
"""O4: shared eval cache must tolerate concurrent writers and never
unlink a DB other processes may hold open."""
import sqlite3
import threading
from pathlib import Path

import chess
import chess.engine

from local_worker.analysis.eval_cache import EvalCache, CachedPv


def _entry() -> list[CachedPv]:
    return [CachedPv(wdl_white=chess.engine.Wdl(wins=1000, draws=0, losses=0),
                      pv_uci=["e2e4"])]


def test_busy_timeout_pragma_set(tmp_path: Path):
    c = EvalCache(tmp_path / "ec.sqlite")
    assert c._conn is not None
    cur = c._conn.execute("PRAGMA busy_timeout")
    assert int(cur.fetchone()[0]) >= 3000
    c.close()


def test_concurrent_writers_no_exception(tmp_path: Path):
    db = tmp_path / "ec.sqlite"
    errors: list[BaseException] = []

    def worker(seed: int) -> None:
        try:
            cache = EvalCache(db)
            for i in range(50):
                z = seed * 1000 + i
                cache.put(z, "net", 1, 1, _entry())
                cache.get(z, "net", 1, 1)
            cache.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [], f"concurrent writers raised: {errors!r}"


def test_corrupt_db_disables_not_unlinks(tmp_path: Path):
    db = tmp_path / "ec.sqlite"
    db.write_bytes(b"this is not a sqlite database, it is garbage" * 10)
    inode_before = db.stat().st_ino

    cache = EvalCache(db)  # must NOT raise, must NOT unlink

    assert db.exists(), "corrupt DB was unlinked — forbidden under multi-proc"
    assert db.stat().st_ino == inode_before, "DB file was replaced"
    assert cache.enabled is False, "corrupt DB should disable the cache"
    # Disabled cache: get/put are silent no-ops, never raise.
    assert cache.get(1, "n", 1, 1) is None
    cache.put(1, "n", 1, 1, _entry())
    cache.close()
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_eval_cache_concurrency.py -q`
Expected: FAIL — `test_busy_timeout_pragma_set` (busy_timeout 0), and `test_corrupt_db_disables_not_unlinks` (current code unlinks + recreates, so `inode` changes / `enabled` stays True).

- [ ] **Step 3: Apply the three O4 changes to `eval_cache.py`**

3a. **busy_timeout on connect.** In `__init__`, replace:

```python
            self._conn = sqlite3.connect(str(db_path))
            self._init_schema()
```
with:
```python
            self._conn = sqlite3.connect(str(db_path), timeout=5.0)
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._init_schema()
```

3b. **Corrupt DB → disable, never unlink.** Replace the entire `except sqlite3.DatabaseError:` block in `_init_schema` (currently logs, `self._conn.close()`, `self.db_path.unlink(missing_ok=True)`, reconnect, `self._init_schema()`) with:

```python
        except sqlite3.DatabaseError:
            # Corrupt/unreadable DB. NEVER unlink — other worker
            # processes may hold this shared file open (O4). Disable
            # this process's cache instead; true corruption is repaired
            # offline (the canonical is rebuilt server-side between
            # campaigns).
            log.warning(
                "eval_cache: corrupt/unreadable DB at %s; disabling cache "
                "for this process (file left intact)", self.db_path,
            )
            try:
                if self._conn is not None:
                    self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
            self.enabled = False
```

3c. **Best-effort degrade on write contention.** In `get()`, wrap the `last_used_at` UPDATE+commit so a lock never propagates. Replace:

```python
        self._conn.execute(
            "UPDATE eval_cache SET last_used_at=? "
            "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
            (int(time.time()), zobrist_signed, network, nodes, multipv),
        )
        self._conn.commit()
        self._hits += 1
        return entries
```
with:
```python
        try:
            self._conn.execute(
                "UPDATE eval_cache SET last_used_at=? "
                "WHERE zobrist=? AND network=? AND nodes=? AND multipv=?",
                (int(time.time()), zobrist_signed, network, nodes, multipv),
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            # Lock contention from a concurrent SF worker. The cache is
            # an optimization — skip the last_used_at bump, still serve
            # the hit. (O4 best-effort degrade.)
            log.debug("eval_cache: skipped last_used_at under lock: %s", exc)
        self._hits += 1
        return entries
```

In `put()`, wrap the write. Replace:

```python
        self._conn.execute(
            "INSERT OR REPLACE INTO eval_cache "
            "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_to_signed64(zobrist), network, nodes, multipv, payload, now, now),
        )
        self._conn.commit()
```
with:
```python
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO eval_cache "
                "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (_to_signed64(zobrist), network, nodes, multipv, payload, now, now),
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            # Concurrent-writer lock; dropping one cache write is
            # harmless (O4 best-effort degrade).
            log.debug("eval_cache: skipped put under lock: %s", exc)
```

- [ ] **Step 4: Run tests, verify pass + no regressions**

Run: `python -m pytest tests/test_eval_cache_concurrency.py tests/ -q -k "eval_cache"`
Expected: PASS (new file 3 passed; existing eval_cache tests still pass).

- [ ] **Step 5: bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/analysis/eval_cache.py
git add services/local_worker/local_worker/analysis/eval_cache.py services/local_worker/tests/test_eval_cache_concurrency.py
git commit -m "fix(worker): eval-cache O4 — busy_timeout, degrade, never unlink shared DB (#130)"
```

---

## Task 4: per-engine log files

**Files:**
- Modify: `services/local_worker/local_worker/logging_setup.py`
- Test: `services/local_worker/tests/test_logging_per_engine.py`

Design: log filename = `{WLW_LOG_BASENAME or "worker"}.log`. When `WLW_LOG_APPEND=1` (set by `onstart.sh` for the N shared-file Stockfish workers) the primary sink is **append + `enqueue=True`** and is **not** truncated; otherwise behaviour is unchanged (truncate, `enqueue=False`) so lc0 and all non-vast callers are unaffected.

- [ ] **Step 1: Write the failing test**

Create `services/local_worker/tests/test_logging_per_engine.py`:

```python
"""Per-engine log routing for the vast fan-out."""
from pathlib import Path

from loguru import logger

from local_worker.logging_setup import configure_logging


def test_basename_routes_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WLW_LOG_BASENAME", "stockfish")
    monkeypatch.setenv("WLW_LOG_APPEND", "1")
    log_file = configure_logging(level="INFO", reset_file=True)
    assert log_file == tmp_path / "stockfish.log"
    logger.info("hello-sf")
    logger.complete()
    assert "hello-sf" in (tmp_path / "stockfish.log").read_text()


def test_append_mode_preserves_prior_content(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WLW_LOG_BASENAME", "stockfish")
    monkeypatch.setenv("WLW_LOG_APPEND", "1")
    target = tmp_path / "stockfish.log"
    target.write_text("PRIOR-LINE\n")
    configure_logging(level="INFO", reset_file=True)
    logger.info("second-proc")
    logger.complete()
    body = target.read_text()
    assert "PRIOR-LINE" in body and "second-proc" in body


def test_default_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("WLW_LOG_BASENAME", raising=False)
    monkeypatch.delenv("WLW_LOG_APPEND", raising=False)
    log_file = configure_logging(level="INFO", reset_file=True)
    assert log_file == tmp_path / "worker.log"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `python -m pytest tests/test_logging_per_engine.py -q`
Expected: FAIL — filename is always `worker.log` (basename ignored).

- [ ] **Step 3: Implement**

In `logging_setup.py`:

3a. Add a helper after `_log_directory()`:

```python
def _log_basename() -> str:
    """Primary log file stem. ``WLW_LOG_BASENAME`` (set per engine by the
    vast entrypoint) selects ``lc0`` / ``stockfish``; default ``worker``."""
    name = os.environ.get("WLW_LOG_BASENAME", "").strip()
    return name or "worker"


def _log_append() -> bool:
    """True when the primary sink must append (shared multi-process file,
    e.g. the N Stockfish workers). Set via ``WLW_LOG_APPEND=1``."""
    return os.environ.get("WLW_LOG_APPEND", "").strip() in {"1", "true", "yes"}
```

3b. Change `_add_primary_sink` to honour append/enqueue. Replace its body with:

```python
def _add_primary_sink(log_file: Path, level: str) -> None:
    """Attach the per-session primary sink.

    Default (lc0 / local): truncate + ``enqueue=False`` (unchanged).
    Append mode (shared Stockfish file across N procs): open in append
    mode with ``enqueue=True`` so concurrent-process writes stay
    record-atomic and the first worker doesn't truncate the others.
    """
    if _log_append():
        logger.add(
            log_file,
            level=level,
            format=_LOG_FORMAT,
            mode="a",
            encoding="utf-8",
            enqueue=True,
        )
        return
    try:
        log_file.unlink(missing_ok=True)
    except OSError:
        pass
    logger.add(
        log_file,
        level=level,
        format=_LOG_FORMAT,
        mode="w",
        encoding="utf-8",
        enqueue=False,
    )
```

3c. In `configure_logging`, change the filename derivation. Replace:

```python
    log_file = log_dir / "worker.log"
    diagnostics_file = log_dir / "worker.diagnostics.log"
```
with:
```python
    basename = _log_basename()
    log_file = log_dir / f"{basename}.log"
    diagnostics_file = log_dir / f"{basename}.diagnostics.log"
```

- [ ] **Step 4: Run tests, verify pass + no regressions**

Run: `python -m pytest tests/test_logging_per_engine.py tests/ -q -k "log"`
Expected: PASS (3 new passed; existing logging tests still pass — default path unchanged).

- [ ] **Step 5: bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/logging_setup.py
git add services/local_worker/local_worker/logging_setup.py services/local_worker/tests/test_logging_per_engine.py
git commit -m "feat(worker): per-engine log files via WLW_LOG_BASENAME/APPEND (#130)"
```

---

## Task 5: upload both engine logs

**Files:**
- Modify: `services/local_worker/local_worker/log_upload.py`

Current `upload_log()` uploads exactly one file (`log_file_path()` from `_log_upload_meta`). For the vast fan-out it must upload each present engine log. Keep all failure-swallowing behaviour.

- [ ] **Step 1: Read `services/local_worker/local_worker/_log_upload_meta.py`** to confirm `log_file_path()` returns the primary log `Path` and `preflight(path)` validates one path. (No edit there.)

- [ ] **Step 2: Modify `upload_log()` to iterate engine logs**

In `log_upload.py`, replace the body from `log_path = log_file_path()` through the `return _parse_response(response)` with a loop over candidate logs in the same directory, uploading each that exists, returning the last successful id (or `-1`):

```python
    base = log_file_path()  # <log_dir>/<basename>.log
    candidates = [base.parent / name for name in
                  ("lc0.log", "stockfish.log", "worker.log")]
    present = [p for p in candidates if p.exists() and p.stat().st_size > 0]
    if not present:
        # Fall back to the single configured log (non-vast callers).
        present = [base] if preflight(base) >= 0 else []

    query = '?force=true' if reason == 'crash' else ''
    url = settings.api_url.rstrip('/') + '/api/v1/worker/logs/' + query
    last_id = -1
    for log_path in present:
        if preflight(log_path) < 0:
            continue
        try:
            with log_path.open('rb') as fh:
                response = httpx.post(
                    url,
                    files={'log': (log_path.name, fh, 'text/plain')},
                    data={'note': note, 'metadata': build_metadata(reason)},
                    headers={'X-Api-Key': settings.api_key},
                    timeout=60.0,
                )
        except (httpx.RequestError, OSError) as exc:
            log.warning('Log upload network/IO error: %s', exc)
            continue
        rid = _parse_response(response)
        if rid >= 0:
            last_id = rid
    return last_id
```

- [ ] **Step 3: Run the existing upload tests**

Run: `python -m pytest tests/ -q -k "upload or log_upload"`
Expected: PASS (existing tests still green; single-file fallback preserves old behaviour).

- [ ] **Step 4: bandit + commit**

```bash
bandit -ll services/local_worker/local_worker/log_upload.py
git add services/local_worker/local_worker/log_upload.py
git commit -m "feat(worker): upload per-engine logs (lc0.log/stockfish.log) (#130)"
```

---

## Task 6: `onstart.sh` fan-out orchestration

**Files:**
- Modify: `services/local_worker/vast/onstart.sh`

Replace the single-lc0 + single-SF launch block with: call `wood-league-worker plan-sf-fanout`, `eval` its env, launch **1 lc0** (basename `lc0`, no append) + **N Stockfish** (basename `stockfish`, append, per-worker `WLW_STOCKFISH_THREADS`/`WLW_STOCKFISH_HASH_MB`/`WLW_MAX_JOBS`), `wait` all, trap unchanged.

- [ ] **Step 1: Read the current `services/local_worker/vast/onstart.sh`.** It currently launches one lc0 (`WLW_WORKER_ID="vast-lc0-..." wood-league-worker --telemetry run --engine lc0 ...`) then one stockfish, both backgrounded, then a checkpoint loop, `trap`, and `wait` on the two PIDs.

- [ ] **Step 2: Replace the launch section.** Replace from the comment `# --- launch both engines concurrently (mirrors runpod/bootstrap.sh) ---` through the two `sf_pid=$!` / engine lines (i.e. the lc0 and stockfish launch pair) with:

```bash
# --- compute Stockfish fan-out for this host ---
eval "$(wood-league-worker plan-sf-fanout)"
echo "onstart: fan-out SF_WORKERS=${SF_WORKERS} SF_THREADS=${SF_THREADS} SF_HASH_MB=${SF_HASH_MB} SF_JOB_SPLIT='${SF_JOB_SPLIT}'"

declare -a engine_pids=()

# lc0 — single GPU-bound process; own truncating log file (lc0.log).
WLW_LOG_BASENAME=lc0 \
WLW_WORKER_ID="vast-lc0-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine lc0 \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
engine_pids+=($!)

# Stockfish — N CPU workers sharing one appended log file (stockfish.log).
read -r -a _sf_split <<< "${SF_JOB_SPLIT}"
for ((i = 0; i < SF_WORKERS; i++)); do
  _cap_arg=""
  if [ -n "${SF_JOB_SPLIT}" ]; then
    _cap_arg="--max-jobs ${_sf_split[$i]}"
  elif [ -n "${WLW_MAX_JOBS:-}" ]; then
    _cap_arg="--max-jobs ${WLW_MAX_JOBS}"
  fi
  WLW_LOG_BASENAME=stockfish WLW_LOG_APPEND=1 \
  WLW_STOCKFISH_THREADS="${SF_THREADS}" WLW_STOCKFISH_HASH_MB="${SF_HASH_MB}" \
  WLW_WORKER_ID="vast-sf-${WL_INSTANCE_ID}-${i}" \
    wood-league-worker --telemetry run --engine stockfish \
    ${_cap_arg} --batch-time "${WLW_BATCH_TIME:-1440}" &
  engine_pids+=($!)
done
```

- [ ] **Step 3: Update the `wait` section.** Replace the two `wait "${lc_pid}"` / `wait "${sf_pid}"` lines (and any `lc_pid`/`sf_pid` references) with:

```bash
# Wait for ALL engine processes (a crash of one does not strand the rest).
for _pid in "${engine_pids[@]}"; do
  wait "${_pid}" || true
done
```

(The `ckpt_pid` checkpoint loop, `final_export` trap, and final `push_delta` stay exactly as they are.)

- [ ] **Step 4: Syntax check**

Run: `bash -n services/local_worker/vast/onstart.sh`
Expected: no output (exit 0).

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/vast/onstart.sh
git commit -m "feat(vast): onstart fan-out — 1 lc0 + N Stockfish, per-engine logs (#130)"
```

---

## Task 7: #129 — Syzygy `https`→`http` + build guard

**Files:**
- Modify: `services/local_worker/vast/Dockerfile`
- Modify (conditional): `services/local_worker/runpod/bootstrap.sh`

- [ ] **Step 1: Read the Syzygy block in `services/local_worker/vast/Dockerfile`.** It is the `RUN` that does `for t in $(curl -fsSL https://tablebase.sesse.net/syzygy/3-4-5/ | grep -oE '[A-Za-z0-9_]+\.(rtbw|rtbz)' | sort -u); do curl -fsSL "https://tablebase.sesse.net/syzygy/3-4-5/$t" -o "/opt/syzygy/$t"; done`.

- [ ] **Step 2: Replace that Syzygy `RUN` with `http://` + a count guard.** Replace the whole `RUN for t in ... done` (the Syzygy tablebase download) with:

```dockerfile
RUN set -eu; \
    base="http://tablebase.sesse.net/syzygy/3-4-5/"; \
    names="$(curl -fsSL "$base" | grep -oE '[A-Za-z0-9_]+\.(rtbw|rtbz)' | sort -u)"; \
    want="$(printf '%s\n' "$names" | grep -c .)"; \
    test "$want" -gt 0 || { echo "FATAL: Syzygy listing empty (http fetch failed)"; exit 1; }; \
    for t in $names; do curl -fsSL "${base}${t}" -o "/opt/syzygy/$t"; done; \
    got="$(ls -1 /opt/syzygy | grep -cE '\.(rtbw|rtbz)$' || true)"; \
    echo "Syzygy: listed=$want downloaded=$got"; \
    test "$got" -eq "$want" || { echo "FATAL: Syzygy incomplete ($got/$want)"; exit 1; }
```

(The `mkdir -p /opt/weights /opt/syzygy` and BT4 download stay as they are — only the Syzygy 3-4-5 loop changes.)

- [ ] **Step 3: Cross-check RunPod.** `grep -n 'tablebase.sesse.net' services/local_worker/runpod/bootstrap.sh`. If any `https://tablebase.sesse.net` appears, change those to `http://` (same reason). If none, no change.

- [ ] **Step 4: Commit**

```bash
git add services/local_worker/vast/Dockerfile services/local_worker/runpod/bootstrap.sh
git commit -m "fix(vast): Syzygy via http:// + build guard; runpod cross-check (#129)"
```

(If `bootstrap.sh` was unchanged, omit it from `git add`.)

---

## Task 8: version bump 0.9.11 → 0.9.12

**Files:**
- Modify: `services/local_worker/pyproject.toml`
- Modify: `services/local_worker/vast/Dockerfile`
- Modify: `.github/workflows/build-vast-worker.yml`

- [ ] **Step 1: Apply all three bumps**

```bash
sed -i '' 's/^version = "0.9.11"/version = "0.9.12"/' services/local_worker/pyproject.toml
sed -i '' 's/ARG WORKER_VERSION=0.9.11/ARG WORKER_VERSION=0.9.12/' services/local_worker/vast/Dockerfile
sed -i '' "s/worker_version || '0.9.11'/worker_version || '0.9.12'/" .github/workflows/build-vast-worker.yml
```

- [ ] **Step 2: Verify**

```bash
grep -n 'version = "0.9' services/local_worker/pyproject.toml
grep -n 'WORKER_VERSION=0.9' services/local_worker/vast/Dockerfile
grep -n "0.9.12" .github/workflows/build-vast-worker.yml
```
Expected: all three show `0.9.12`.

- [ ] **Step 3: Commit**

```bash
git add services/local_worker/pyproject.toml services/local_worker/vast/Dockerfile .github/workflows/build-vast-worker.yml
git commit -m "chore(worker): bump 0.9.11 -> 0.9.12 (kill stale WORKER_VERSION defaults)"
```

---

## Task 9: quality gate, docs, PR, release/validation checklist

**Files:**
- Modify: `services/local_worker/vast/README.md`
- Modify: wiki `wood_league.wiki/Optional-Deployment-via-Vast.ai.md` (+ `Vast.ai-Deployment.md` if needed)

- [ ] **Step 1: Full worker quality gate** (from `services/local_worker`, venv active), per project standard:

```bash
ruff check . && \
bandit -ll -r local_worker && \
python -m pytest tests/ -q
```
Plus the project's full ordered gate ([[feedback-quality-gate]]): ruff → bandit+semgrep → radon/xenon → mypy → pytest+cov. Fix any new findings before proceeding. (`semgrep`, `radon`, `xenon`, `mypy` are in the worker dev deps; run as the project normally does — see prior worker commits / CONTRIBUTING.)

- [ ] **Step 2: Update the vast runbook** `services/local_worker/vast/README.md`: note the **per-engine log paths** (`lc0.log`, `stockfish.log` — not `worker.log`), the **auto-fan-out** behaviour (operator no longer sets SF threads/workers; `WLW_MAX_JOBS` stays the per-engine total and is partitioned across SF workers), and the **Syzygy fix**. Commit.

- [ ] **Step 3: Update the wiki** (`wood_league.wiki` is a sibling git repo; signed commits — if commit fails with an ssh-askpass error, the operator must `ssh-add ~/.ssh/gitHub_ed25519` first). Update `Optional-Deployment-via-Vast.ai.md`: per-engine log tailing (`vastai logs` shows stdout TUI; the real per-engine logs are `…/log/lc0.log` / `…/log/stockfish.log`), fan-out behaviour, Syzygy. Plain tone, cross-linked ([[feedback-wiki-tone]]). Commit + push wiki `master`.

- [ ] **Step 4: Push branch + open PR**

```bash
git push -u origin issue/130-vast-sf-fanout-per-engine-logs
gh pr create --title "vast: SF auto-fan-out + per-engine logs + eval-cache O4; Syzygy http (#130, #129)" \
  --body "Implements docs/superpowers/specs/2026-05-16-vast-sf-fanout-per-engine-logs-design.md. Closes #130. Closes #129." \
  --base main
```

- [ ] **Step 5: Release chain** (after PR merge — proven sequence from worker history): tag `worker-v0.9.12` → wait for **Publish wood-league-worker to PyPI** green → confirm `pip index`/PyPI shows `0.9.12` → tag `vast-worker-v0.9.12` → wait for **build-vast-worker** green (the new Syzygy + existing TRT build guards must pass).

- [ ] **Step 6: One live L40S validation** (per spec; vast on-demand never self-stops — **destroy after**):
  - Operator re-points the vast template image tag to `vast-worker-v0.9.12` (templates are replace-on-edit — recreate with the full one-shot POST incl. all 7 env vars + GHCR `docker_login_pass`; verify via the template API before launch).
  - Launch cheapest L40S: `vastai create instance <id> --template_hash <hash> --disk 40 --env '-e WLW_MAX_JOBS=12 -e WL_CAMPAIGN_ID=fanout-validate -e WL_SKIP_CACHE_PULL=1'`.
  - Confirm via `vastai logs <id>` + SSH `tail` of `/root/.local/state/wood-league-worker/log/{lc0,stockfish}.log`: plan-sf-fanout line printed; **N** SF procs (`ps`); `lc0.log` and `stockfish.log` are **separate**; CPU well above the old ~19%; no `database is locked`; `Found N>0 … Syzygy`; both engines process games (`Games processed > 0`); cache delta uploads.
  - `vastai destroy instance <id> -y`.

- [ ] **Step 7: Final commit / checkpoint** the README change and update the resume memory (mark #130/#129 shipped).

---

## Self-review (completed by plan author)

**Spec coverage:** auto-size heuristic → Task 1 (exact constants/algorithm match spec). `WLW_MAX_JOBS` partition → Task 1 `_split_jobs` + Task 6 consumption. plan-sf-fanout CLI → Task 2. onstart 1 lc0 + N SF → Task 6. O4 (busy_timeout/degrade/no-unlink) → Task 3. Per-engine 2-file logs (append+enqueue for shared SF) → Task 4. Upload both → Task 5. #129 http + count guard + runpod cross-check → Task 7. One 0.9.12 release + stale-default kill → Task 8. Testing surface (pure helper table, concurrency, logging) → Tasks 1/3/4. Docs + release + single live validation → Task 9. **No spec requirement is unmapped.**

**Placeholder scan:** every code step shows complete code; every command shows expected output; no TBD/TODO. The few "read the current file first" steps are followed by the exact old→new replacement.

**Type consistency:** `FanoutPlan(workers, threads, hash_mb, job_split)` defined in Task 1 and consumed identically by Task 2 (`plan.workers/threads/hash_mb/job_split`) and Task 6 (`SF_WORKERS/SF_THREADS/SF_HASH_MB/SF_JOB_SPLIT`). `WLW_LOG_BASENAME`/`WLW_LOG_APPEND` defined in Task 4 and set in Task 6 with the same names. `WLW_STOCKFISH_THREADS`/`WLW_STOCKFISH_HASH_MB`/`WLW_MAX_JOBS` are pre-existing `config.py` env overrides (confirmed `_INT_ENV_FIELDS` + `_apply_max_jobs_override`) — Task 6 sets them; no worker-code change needed.

**Known follow-ups (out of scope, do not implement here):** #131 (move-quality label-case mismatch — app-side, separate PR); #128 (Analysis Queue Dashboard — separate).
