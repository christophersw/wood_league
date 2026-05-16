# vast.ai Bulk Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the existing `wood-league-worker` on vast.ai for bulk chess analysis from a self-contained baked private image, with the engine eval-cache pulled at boot and checkpointed back to object storage (no host-scoped volume), lc0 and Stockfish running concurrently in one instance.

**Architecture:** A baked private Docker image carries all stable assets (CUDA/cuDNN, lc0+TRT, BT4 weights, Syzygy 3-4-5, TensorRT, the pinned worker, the calibration-cache seed). An `--onstart` entrypoint — mirroring the proven RunPod `bootstrap.sh` two-process pattern — pulls the canonical eval cache (fail-soft), launches `--engine lc0` and `--engine stockfish` worker processes concurrently against one shared WAL SQLite cache, periodically and on exit snapshots and uploads the instance's cache delta, and exits when both bounded worker processes finish. A manual server-side merge job unions per-instance deltas into the next canonical between campaigns.

**Tech Stack:** Python 3.11, Typer CLI, stdlib `sqlite3` (WAL, `VACUUM INTO`), `boto3` (S3-compatible Railway object storage), Docker, GitHub Actions, vast.ai CLI.

**Spec:** `docs/superpowers/specs/2026-05-15-vastai-bulk-worker-design.md`

---

## Context

Issue #119 proved the lc0 `onnx-trt` backend is worth shipping on Ada GPUs, but RunPod had no L40 available — forcing production to pivot RunPod → vast.ai. vast.ai volumes are strictly host-scoped, which breaks RunPod's "one region volume any pod reuses" provisioning/caching model. This plan delivers the provisioning + caching layer for that pivot. The worker core is platform-agnostic (an HTTP pull client fed by `WLW_*` env), so this is a deployment/caching change, not a worker rewrite — the only worker-code additions are two small, independently-testable modules (cache sync, cache merge) plus a CLI command; the existing analysis loop is untouched.

## Prerequisites (HARD — read before executing)

- **Sub-project E (`--max-jobs` run cap) must land first.** It is a separate
  approved spec (`docs/superpowers/specs/2026-05-15-worker-max-jobs-run-cap-design.md`)
  with its own plan. E adds `--max-jobs` / `WLW_MAX_JOBS` and one-at-a-time
  checkout; verified **not implemented** today. The vast entrypoint
  (Task 9) sets `WLW_MAX_JOBS` so each engine process self-terminates.
  Until E lands, the entrypoint still works but each engine drains until
  queue-empty / `--batch-time` instead of a job count. **Tasks 1–8 and
  10–12 do not depend on E and can be implemented now.** Task 9's bounded
  behaviour is fully realized only after E.
- A private container registry (GHCR private repo or Docker Hub private)
  with push credentials available to CI and pull credentials configured on
  the vast.ai account (`vastai` registry auth).
- Railway object-storage bucket reachable via the S3-compatible env vars
  already used by `services/app/api/log_storage.py`:
  `RAILWAY_BUCKET_NAME`, `ENDPOINT`, `REGION`, `ACCESS_KEY_ID`,
  `SECRET_ACCESS_KEY`.

## File Structure

**Create:**
- `services/local_worker/local_worker/cache_sync.py` — boot-time cache pull, WAL-safe snapshot, delta upload. Pure functions; injectable S3 client for testing.
- `services/local_worker/local_worker/cache_merge.py` — offline union of per-instance deltas into canonical (INSERT OR REPLACE) + prune + vacuum. Reuses `EvalCache` for schema/prune (DRY).
- `services/local_worker/tests/test_cache_sync.py` — unit tests.
- `services/local_worker/tests/test_cache_merge.py` — unit tests.
- `services/local_worker/vast/onstart.sh` — vast `--onstart` entrypoint (mirrors `runpod/bootstrap.sh`).
- `services/local_worker/vast/Dockerfile` — baked private image.
- `services/local_worker/vast/README.md` — operator launch recipe + env contract.
- `.github/workflows/build-vast-worker.yml` — build/push the private image.

**Modify:**
- `services/local_worker/pyproject.toml` — add `boto3` dep; bump `version` 0.9.6 → 0.9.7.
- `services/local_worker/local_worker/cli.py` — add `cache-merge` Typer command.

**Reused (do not modify):**
- `services/local_worker/local_worker/analysis/eval_cache.py` — `EvalCache` (schema, `prune(max_bytes)`); table `eval_cache`, PK `(zobrist, network, nodes, multipv)`.
- `services/local_worker/local_worker/_shared.py:44-61` — `data_dir()`; `WLW_DATA_DIR` overrides the eval-cache directory.
- `services/local_worker/local_worker/loop.py:135-168` — `_open_eval_cache`; cache lives at `data_dir()/eval_cache.sqlite`.
- `services/app/api/log_storage.py` — boto3 `_client()` pattern to mirror (Django-coupled; cannot be imported by the standalone worker package).
- `services/local_worker/runpod/bootstrap.sh:150-181` — proven two-process (lc0 + stockfish) launch+wait pattern to mirror.

---

## Task 1: Worker dependency + version bump

**Files:**
- Modify: `services/local_worker/pyproject.toml`

- [ ] **Step 1: Add boto3 and bump version**

In `services/local_worker/pyproject.toml`, change `version = "0.9.6"` to
`version = "0.9.7"`, and add `"boto3>=1.34"` to the `[project]`
`dependencies` array (same lower bound as `services/app`).

- [ ] **Step 2: Verify the package still resolves**

Run: `cd services/local_worker && python -m pip install -e . --dry-run`
Expected: resolves with `boto3` listed, no errors.

- [ ] **Step 3: Commit**

```bash
git add services/local_worker/pyproject.toml
git commit -m "build(worker): add boto3 dep, bump 0.9.6 -> 0.9.7 for vast cache sync"
```

---

## Task 2: cache_sync — WAL-safe snapshot

**Files:**
- Create: `services/local_worker/local_worker/cache_sync.py`
- Test: `services/local_worker/tests/test_cache_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_cache_sync.py
import sqlite3
from pathlib import Path

from local_worker.cache_sync import snapshot_db


def test_snapshot_db_produces_valid_copy_under_open_wal(tmp_path: Path):
    src = tmp_path / "eval_cache.sqlite"
    conn = sqlite3.connect(src)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (k INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES (1, 'a')")
    conn.commit()
    # Leave the WAL connection OPEN to mimic a running worker.

    dst = tmp_path / "snap.sqlite"
    snapshot_db(src, dst)

    assert dst.exists()
    snap = sqlite3.connect(dst)
    rows = snap.execute("SELECT k, v FROM t").fetchall()
    assert rows == [(1, "a")]
    snap.close()
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py::test_snapshot_db_produces_valid_copy_under_open_wal -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'local_worker.cache_sync'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/local_worker/local_worker/cache_sync.py
"""
Title: cache_sync.py — vast.ai eval-cache boot pull / checkpoint upload
Description:
    Pulls the canonical engine eval cache from S3-compatible object
    storage at instance boot (fail-soft) and uploads WAL-safe snapshots
    of this instance's cache as per-campaign/per-instance deltas. No
    host-scoped volume is involved; the canonical compounds across
    campaigns via the offline merge job (cache_merge.py).
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)


def snapshot_db(src: Path, dst: Path) -> None:
    """Write a consistent copy of a (possibly WAL-active) SQLite DB.

    Uses ``VACUUM INTO`` so a snapshot can be taken while worker
    processes hold the source open in WAL mode. ``VACUUM INTO`` reads a
    consistent transaction and writes a fully-checkpointed standalone DB.

    Args:
        src: Path to the live eval-cache SQLite file.
        dst: Destination path for the snapshot (overwritten if present).
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    conn = sqlite3.connect(str(src))
    try:
        conn.execute("VACUUM INTO ?", (str(dst),))
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/local_worker/cache_sync.py services/local_worker/tests/test_cache_sync.py
git commit -m "feat(worker): WAL-safe eval-cache snapshot (cache_sync.snapshot_db)"
```

---

## Task 3: cache_sync — S3 client factory + key helpers

**Files:**
- Modify: `services/local_worker/local_worker/cache_sync.py`
- Test: `services/local_worker/tests/test_cache_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# append to services/local_worker/tests/test_cache_sync.py
import local_worker.cache_sync as cs


def test_checkpoint_key_layout():
    assert cs.CANONICAL_KEY == "eval_cache/canonical.sqlite"
    assert (
        cs.checkpoint_key("camp-1", "inst-9")
        == "eval_cache/checkpoints/camp-1/inst-9.sqlite"
    )


def test_make_s3_client_uses_railway_env(monkeypatch):
    captured = {}

    def fake_boto3_client(service, **kwargs):
        captured["service"] = service
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setenv("RAILWAY_BUCKET_NAME", "wl-bucket")
    monkeypatch.setenv("ENDPOINT", "https://s3.example.com")
    monkeypatch.setenv("REGION", "us-east-1")
    monkeypatch.setenv("ACCESS_KEY_ID", "AK")
    monkeypatch.setenv("SECRET_ACCESS_KEY", "SK")
    monkeypatch.setattr(cs.boto3, "client", fake_boto3_client)

    client, bucket = cs.make_s3_client()

    assert bucket == "wl-bucket"
    assert captured["service"] == "s3"
    assert captured["kwargs"]["endpoint_url"] == "https://s3.example.com"
    assert captured["kwargs"]["region_name"] == "us-east-1"
    assert captured["kwargs"]["aws_access_key_id"] == "AK"
    assert captured["kwargs"]["aws_secret_access_key"] == "SK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py::test_make_s3_client_uses_railway_env -v`
Expected: FAIL — `AttributeError: module 'local_worker.cache_sync' has no attribute 'boto3'`

- [ ] **Step 3: Write minimal implementation**

Add to the top imports of `cache_sync.py` (after `import sqlite3`):

```python
import os

import boto3
```

Add below `log = logging.getLogger(__name__)`:

```python
CANONICAL_KEY = "eval_cache/canonical.sqlite"


def checkpoint_key(campaign_id: str, instance_id: str) -> str:
    """Return the per-campaign/per-instance object key for a cache delta.

    Args:
        campaign_id: Logical campaign identifier (``WL_CAMPAIGN_ID``).
        instance_id: Stable per-instance identifier (``WL_INSTANCE_ID``).

    Returns:
        Object key, e.g. ``eval_cache/checkpoints/<campaign>/<instance>.sqlite``.
    """
    return f"eval_cache/checkpoints/{campaign_id}/{instance_id}.sqlite"


def make_s3_client() -> tuple[object, str]:
    """Build an S3 client for the Railway-compatible bucket from env.

    Mirrors ``services/app/api/log_storage.py`` but reads ``os.environ``
    directly (the worker is a standalone package and cannot import the
    Django app). Env vars: ``RAILWAY_BUCKET_NAME``, ``ENDPOINT``,
    ``REGION`` (default ``us-east-1``), ``ACCESS_KEY_ID``,
    ``SECRET_ACCESS_KEY``.

    Returns:
        ``(client, bucket_name)``.
    """
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT") or None,
        region_name=os.environ.get("REGION", "us-east-1"),
        aws_access_key_id=os.environ.get("ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("SECRET_ACCESS_KEY"),
    )
    return client, os.environ.get("RAILWAY_BUCKET_NAME", "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -v`
Expected: PASS (all three)

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/local_worker/cache_sync.py services/local_worker/tests/test_cache_sync.py
git commit -m "feat(worker): S3 client factory + cache key helpers (cache_sync)"
```

---

## Task 4: cache_sync — fail-soft canonical pull

**Files:**
- Modify: `services/local_worker/local_worker/cache_sync.py`
- Test: `services/local_worker/tests/test_cache_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# append to services/local_worker/tests/test_cache_sync.py
class _FakeClient:
    def __init__(self, *, raise_on_download=False):
        self.raise_on_download = raise_on_download
        self.downloaded = None

    def download_file(self, bucket, key, dest):
        if self.raise_on_download:
            raise RuntimeError("no such key")
        self.downloaded = (bucket, key, dest)
        Path(dest).write_bytes(b"SQLITE-BYTES")


def test_pull_canonical_writes_file_on_success(tmp_path):
    client = _FakeClient()
    dest = tmp_path / "eval_cache.sqlite"
    ok = cs.pull_canonical(client, "wl-bucket", dest)
    assert ok is True
    assert dest.read_bytes() == b"SQLITE-BYTES"
    assert client.downloaded == ("wl-bucket", cs.CANONICAL_KEY, str(dest))


def test_pull_canonical_failsoft_on_missing(tmp_path):
    client = _FakeClient(raise_on_download=True)
    dest = tmp_path / "eval_cache.sqlite"
    ok = cs.pull_canonical(client, "wl-bucket", dest)
    assert ok is False           # never raises
    assert not dest.exists()     # no partial file left behind
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -k pull_canonical -v`
Expected: FAIL — `AttributeError: ... has no attribute 'pull_canonical'`

- [ ] **Step 3: Write minimal implementation**

Add to `cache_sync.py`:

```python
def pull_canonical(client: object, bucket: str, dest: Path) -> bool:
    """Download the canonical eval cache to ``dest``. Never raises.

    Fail-soft: any error (missing object, network, auth) logs a warning
    and returns False so the worker starts with an empty cache and the
    campaign still runs. A partially written file is removed on failure.

    Args:
        client: An S3 client exposing ``download_file(bucket, key, dest)``.
        bucket: Bucket name.
        dest: Local path to write the canonical cache to.

    Returns:
        True if the canonical cache was fetched, False otherwise.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, CANONICAL_KEY, str(dest))
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
        log.warning("cache_sync: canonical pull failed (%s); starting empty", exc)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/local_worker/cache_sync.py services/local_worker/tests/test_cache_sync.py
git commit -m "feat(worker): fail-soft canonical eval-cache pull (cache_sync.pull_canonical)"
```

---

## Task 5: cache_sync — delta upload (snapshot + put)

**Files:**
- Modify: `services/local_worker/local_worker/cache_sync.py`
- Test: `services/local_worker/tests/test_cache_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# append to services/local_worker/tests/test_cache_sync.py
import sqlite3 as _sqlite3


class _UploadClient:
    def __init__(self):
        self.uploaded = None

    def upload_file(self, src, bucket, key):
        self.uploaded = (src, bucket, key)


def test_upload_delta_snapshots_then_uploads(tmp_path):
    live = tmp_path / "eval_cache.sqlite"
    conn = _sqlite3.connect(live)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (k INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()  # leave open (running worker)

    client = _UploadClient()
    cs.upload_delta(client, "wl-bucket", live, "camp-1", "inst-9", tmp_path)

    src, bucket, key = client.uploaded
    assert bucket == "wl-bucket"
    assert key == "eval_cache/checkpoints/camp-1/inst-9.sqlite"
    # uploaded artifact is a valid, separate snapshot, not the live file
    assert src != str(live)
    snap = _sqlite3.connect(src)
    assert snap.execute("SELECT k FROM t").fetchall() == [(1,)]
    snap.close()
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -k upload_delta -v`
Expected: FAIL — `AttributeError: ... has no attribute 'upload_delta'`

- [ ] **Step 3: Write minimal implementation**

Add to `cache_sync.py`:

```python
def upload_delta(
    client: object,
    bucket: str,
    live_db: Path,
    campaign_id: str,
    instance_id: str,
    work_dir: Path,
) -> None:
    """Snapshot the live cache and upload it as this instance's delta.

    A WAL-safe snapshot is taken first (the worker keeps the DB open),
    then uploaded under the per-campaign/per-instance key, overwriting
    only this instance's own object. Errors are logged, not raised — a
    failed checkpoint must never interrupt analysis.

    Args:
        client: S3 client exposing ``upload_file(src, bucket, key)``.
        bucket: Bucket name.
        live_db: Path to the live eval-cache SQLite file.
        campaign_id: ``WL_CAMPAIGN_ID``.
        instance_id: ``WL_INSTANCE_ID``.
        work_dir: Directory for the transient snapshot file.
    """
    if not live_db.exists():
        log.info("cache_sync: no live cache yet; skipping checkpoint")
        return
    snap = work_dir / "eval_cache.snapshot.sqlite"
    try:
        snapshot_db(live_db, snap)
        client.upload_file(str(snap), bucket, checkpoint_key(campaign_id, instance_id))
    except Exception as exc:  # noqa: BLE001 — checkpoint must not break the run
        log.warning("cache_sync: delta upload failed (%s); will retry next cycle", exc)
    finally:
        if snap.exists():
            snap.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_cache_sync.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/local_worker/local_worker/cache_sync.py services/local_worker/tests/test_cache_sync.py
git commit -m "feat(worker): snapshot+upload eval-cache delta (cache_sync.upload_delta)"
```

---

## Task 6: cache_merge — union deltas into canonical

**Files:**
- Create: `services/local_worker/local_worker/cache_merge.py`
- Test: `services/local_worker/tests/test_cache_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# services/local_worker/tests/test_cache_merge.py
import sqlite3
from pathlib import Path

from local_worker.analysis.eval_cache import EvalCache
from local_worker.cache_merge import merge_deltas


def _seed(path: Path, rows):
    """rows: list of (zobrist, network, nodes, multipv, payload, ts)."""
    cache = EvalCache(path)  # creates schema (table eval_cache)
    cache.close()
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT OR REPLACE INTO eval_cache "
        "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [(z, n, nd, m, p, ts, ts) for (z, n, nd, m, p, ts) in rows],
    )
    conn.commit()
    conn.close()


def test_merge_unions_and_last_writer_wins(tmp_path):
    canonical = tmp_path / "canonical.sqlite"
    d1 = tmp_path / "d1.sqlite"
    d2 = tmp_path / "d2.sqlite"
    _seed(canonical, [(1, "BT4", 100, 3, '{"v":2,"pvs":[]}', 10)])
    _seed(d1, [(2, "BT4", 100, 3, '{"v":2,"pvs":[]}', 20)])
    # same PK as canonical row 1, newer ts -> should win
    _seed(d2, [(1, "BT4", 100, 3, '{"v":2,"pvs":[{"w":1}]}', 99)])

    merged = merge_deltas(canonical, [d1, d2], max_bytes=50 * 1024 * 1024)

    conn = sqlite3.connect(canonical)
    rows = dict(
        (z, payload)
        for (z, payload) in conn.execute(
            "SELECT zobrist, payload FROM eval_cache"
        ).fetchall()
    )
    conn.close()
    assert set(rows) == {1, 2}                       # union
    assert rows[1] == '{"v":2,"pvs":[{"w":1}]}'      # last-writer-wins
    assert merged == 2                               # rows in canonical
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'local_worker.cache_merge'`

- [ ] **Step 3: Write minimal implementation**

```python
# services/local_worker/local_worker/cache_merge.py
"""
Title: cache_merge.py — offline per-instance eval-cache delta merge
Description:
    Server-side, manual, between-campaigns job. Unions per-instance
    cache deltas into the canonical eval cache using INSERT OR REPLACE
    on the (zobrist, network, nodes, multipv) primary key. The engine is
    deterministic at fixed nodes, so identical positions yield identical
    evals — last-writer-wins is correct. The canonical is then pruned to
    the size cap and vacuumed, and becomes the next campaign's
    boot-time-pull source. Intentionally one campaign behind.
Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from local_worker.analysis.eval_cache import EvalCache

log = logging.getLogger(__name__)


def merge_deltas(canonical: Path, deltas: list[Path], max_bytes: int) -> int:
    """Union delta caches into the canonical, prune, vacuum.

    Args:
        canonical: Path to the canonical eval-cache SQLite file. Created
            (with schema) if it does not exist.
        deltas: Per-instance delta SQLite files, applied in list order
            (later files win on primary-key collisions).
        max_bytes: Size cap enforced via ``EvalCache.prune`` after merge.

    Returns:
        Number of rows in the canonical after merge + prune.
    """
    # Ensure canonical exists with the current schema (reuses EvalCache).
    EvalCache(canonical).close()

    conn = sqlite3.connect(str(canonical))
    try:
        for delta in deltas:
            if not Path(delta).exists():
                log.warning("cache_merge: delta missing, skipped: %s", delta)
                continue
            conn.execute("ATTACH DATABASE ? AS d", (str(delta),))
            conn.execute(
                "INSERT OR REPLACE INTO eval_cache "
                "(zobrist, network, nodes, multipv, payload, "
                " created_at, last_used_at) "
                "SELECT zobrist, network, nodes, multipv, payload, "
                "       created_at, last_used_at FROM d.eval_cache"
            )
            conn.commit()
            conn.execute("DETACH DATABASE d")
    finally:
        conn.close()

    cache = EvalCache(canonical)
    try:
        cache.prune(max_bytes)  # prune VACUUMs only if it evicted
        rows = cache.stats().rows
    finally:
        cache.close()
    # Always compact after the union (prune may not have run a VACUUM).
    vac = sqlite3.connect(str(canonical))
    try:
        vac.execute("VACUUM")
    finally:
        vac.close()
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_cache_merge.py -v`
Expected: PASS

- [ ] **Step 5: Add the v1-schema-tolerance test**

```python
# append to services/local_worker/tests/test_cache_merge.py
def test_merge_copies_rows_verbatim_including_legacy(tmp_path):
    """v1 payloads are copied raw; readers already treat v1 as a miss."""
    canonical = tmp_path / "canonical.sqlite"
    d1 = tmp_path / "d1.sqlite"
    _seed(canonical, [])
    _seed(d1, [(7, "BT4", 100, 3, '{"v":1,"pvs":[]}', 5)])
    rows = merge_deltas(canonical, [d1], max_bytes=50 * 1024 * 1024)
    assert rows == 1
    conn = sqlite3.connect(canonical)
    assert conn.execute(
        "SELECT payload FROM eval_cache WHERE zobrist=7"
    ).fetchone()[0] == '{"v":1,"pvs":[]}'
    conn.close()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_cache_merge.py -v`
Expected: PASS (both tests)

- [ ] **Step 7: Commit**

```bash
git add services/local_worker/local_worker/cache_merge.py services/local_worker/tests/test_cache_merge.py
git commit -m "feat(worker): offline eval-cache delta merge (cache_merge.merge_deltas)"
```

---

## Task 7: CLI — `cache-merge` command

**Files:**
- Modify: `services/local_worker/local_worker/cli.py`
- Test: `services/local_worker/tests/test_cache_merge_cli.py` (create)

- [ ] **Step 1: Inspect the CLI module**

Run: `cd services/local_worker && python -c "import local_worker.cli as c; print(c.__file__)"`
Then open `local_worker/cli.py` and confirm the Typer app object name (it
is `app`, registered as `local_worker.cli:app` in `pyproject.toml`) and
how existing subcommands are registered. Match that exact registration
style in Step 3.

- [ ] **Step 2: Write the failing test**

```python
# services/local_worker/tests/test_cache_merge_cli.py
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from local_worker.cli import app
from local_worker.analysis.eval_cache import EvalCache


def test_cache_merge_command(tmp_path: Path):
    canonical = tmp_path / "canonical.sqlite"
    delta = tmp_path / "d1.sqlite"
    EvalCache(canonical).close()
    EvalCache(delta).close()
    conn = sqlite3.connect(delta)
    conn.execute(
        "INSERT INTO eval_cache "
        "(zobrist, network, nodes, multipv, payload, created_at, last_used_at) "
        "VALUES (1,'BT4',100,3,'{\"v\":2,\"pvs\":[]}',1,1)"
    )
    conn.commit()
    conn.close()

    result = CliRunner().invoke(
        app,
        ["cache-merge", "--canonical", str(canonical),
         "--delta", str(delta), "--max-mb", "50"],
    )
    assert result.exit_code == 0, result.output
    assert "merged" in result.output.lower()
    out = sqlite3.connect(canonical)
    assert out.execute("SELECT COUNT(*) FROM eval_cache").fetchone()[0] == 1
    out.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_cache_merge_cli.py -v`
Expected: FAIL — `cache-merge` is not a known command (non-zero exit / "No such command").

- [ ] **Step 4: Add the command**

Append to `local_worker/cli.py` (use the existing `app` Typer instance and
the module's existing `import typer`; add `from pathlib import Path` and
`from local_worker.cache_merge import merge_deltas` if not already
imported):

```python
@app.command("cache-merge")
def cache_merge(
    canonical: Path = typer.Option(..., help="Canonical eval-cache SQLite path"),
    delta: list[Path] = typer.Option(
        ..., "--delta", help="Per-instance delta SQLite path (repeatable)"
    ),
    max_mb: int = typer.Option(500, help="Canonical size cap in MB"),
) -> None:
    """Merge per-instance eval-cache deltas into the canonical (offline).

    Server-side, manual, between-campaigns. Unions each --delta into
    --canonical (last-writer-wins on primary-key collision), prunes to
    --max-mb, and vacuums.
    """
    rows = merge_deltas(canonical, list(delta), max_bytes=max_mb * 1024 * 1024)
    typer.echo(f"merged: canonical now has {rows} rows")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/local_worker && python -m pytest tests/test_cache_merge_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/local_worker/local_worker/cli.py services/local_worker/tests/test_cache_merge_cli.py
git commit -m "feat(worker): cache-merge CLI command for offline delta merge"
```

---

## Task 8: Full worker test + quality gate

**Files:** none (verification only)

- [ ] **Step 1: Run the worker test suite**

Run: `cd services/local_worker && source ../../.venv/bin/activate && python -m pytest -q`
Expected: PASS — no regressions in existing `eval_cache` / `loop` suites,
plus the new `test_cache_sync`, `test_cache_merge`, `test_cache_merge_cli`.

- [ ] **Step 2: Run the project quality gate on changed files**

Run, in order, on the new/modified files (`cache_sync.py`, `cache_merge.py`,
`cli.py`, tests): `ruff check` → `bandit` + `semgrep` → `radon`/`xenon`
→ `mypy` → `pytest --cov`. (This is the established 5-stage pipeline; fix
any finding before proceeding.)
Expected: all stages clean.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "chore(worker): quality-gate fixes for cache sync/merge"
```

(Skip if Step 2 produced no changes.)

---

## Task 9: vast `--onstart` entrypoint

**Files:**
- Create: `services/local_worker/vast/onstart.sh`

> **E coupling:** `WLW_MAX_JOBS` is consumed by sub-project E. Until E
> lands, each engine drains until queue-empty / `--batch-time`; the
> script is still correct (the periodic + trap + final export and the
> two-process model do not require E). Do not remove the `WLW_MAX_JOBS`
> export — it activates automatically once E ships.

- [ ] **Step 1: Create the entrypoint script**

Create `services/local_worker/vast/onstart.sh` with mode `+x`. It mirrors
`services/local_worker/runpod/bootstrap.sh:150-181` (two parallel engine
processes, wait both) and adds the cache lifecycle:

```bash
#!/usr/bin/env bash
# Title: onstart.sh — vast.ai entrypoint for the bulk analysis worker
# Description:
#   Pulls the canonical eval cache (fail-soft), launches lc0 + Stockfish
#   worker processes concurrently against one shared WAL cache,
#   periodically and on exit snapshots+uploads this instance's cache
#   delta, and exits when both bounded workers finish. No host volume.
# Changelog:
#   2026-05-15: Initial creation (vast.ai bulk worker plan, A+B).
set -euo pipefail

: "${WL_CAMPAIGN_ID:?WL_CAMPAIGN_ID is required}"
WL_INSTANCE_ID="${WL_INSTANCE_ID:-$(hostname)-$$}"
WL_CACHE_CHECKPOINT_MINUTES="${WL_CACHE_CHECKPOINT_MINUTES:-10}"
export WLW_DATA_DIR="${WLW_DATA_DIR:-/data/wlw}"
CACHE_DB="${WLW_DATA_DIR}/eval_cache.sqlite"
WORK_DIR="${WLW_DATA_DIR}/.sync"
mkdir -p "${WLW_DATA_DIR}" "${WORK_DIR}"

py() { python -c "$1"; }

pull_cache() {
  if [ "${WL_SKIP_CACHE_PULL:-0}" = "1" ]; then
    echo "onstart: WL_SKIP_CACHE_PULL=1, starting with empty cache"
    return 0
  fi
  py "
import os
from pathlib import Path
from local_worker.cache_sync import make_s3_client, pull_canonical
c,b = make_s3_client()
ok = pull_canonical(c, b, Path(os.environ['_CACHE_DB']))
print('onstart: canonical pull ok' if ok else 'onstart: canonical pull failed (empty)')
" || true
}

push_delta() {
  py "
import os
from pathlib import Path
from local_worker.cache_sync import make_s3_client, upload_delta
c,b = make_s3_client()
upload_delta(c, b, Path(os.environ['_CACHE_DB']),
             os.environ['WL_CAMPAIGN_ID'], os.environ['WL_INSTANCE_ID'],
             Path(os.environ['_WORK_DIR']))
" || true
}

export _CACHE_DB="${CACHE_DB}" _WORK_DIR="${WORK_DIR}"

pull_cache

# --- launch both engines concurrently (mirrors runpod/bootstrap.sh) ---
WLW_WORKER_ID="vast-lc0-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine lc0 \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
lc_pid=$!

WLW_WORKER_ID="vast-sf-${WL_INSTANCE_ID}" \
  wood-league-worker --telemetry run --engine stockfish \
  ${WLW_MAX_JOBS:+--max-jobs "${WLW_MAX_JOBS}"} --batch-time "${WLW_BATCH_TIME:-1440}" &
sf_pid=$!

# --- periodic checkpoint loop ---
( while sleep "$((WL_CACHE_CHECKPOINT_MINUTES * 60))"; do push_delta; done ) &
ckpt_pid=$!

final_export() {
  kill "${ckpt_pid}" 2>/dev/null || true
  push_delta
}
trap 'final_export' TERM INT

# Wait for BOTH engine processes (a crash of one does not strand the other).
wait "${lc_pid}" || true
wait "${sf_pid}" || true

kill "${ckpt_pid}" 2>/dev/null || true
trap - TERM INT
push_delta
echo "onstart: both engines exited; final delta uploaded; instance done"
```

- [ ] **Step 2: Lint the script**

Run: `shellcheck services/local_worker/vast/onstart.sh`
Expected: no errors (warnings about `py` heredoc interpolation of
`_CACHE_DB`/`_WORK_DIR` are acceptable — they are passed via exported env,
not shell-expanded into Python source).

- [ ] **Step 3: Make executable and commit**

```bash
chmod +x services/local_worker/vast/onstart.sh
git add services/local_worker/vast/onstart.sh
git commit -m "feat(vast): --onstart entrypoint (concurrent dual-engine + cache lifecycle)"
```

---

## Task 10: Baked private image Dockerfile

**Files:**
- Create: `services/local_worker/vast/Dockerfile`

- [ ] **Step 1: Inspect the RunPod Dockerfile for reuse**

Open `services/local_worker/Dockerfile` and reuse its proven asset
acquisition steps (CUDA base choice, lc0 binary install, Stockfish apt,
worker pip install). The vast image differs in three ways: assets are
**baked, not volume-mounted**; the eval cache is **not** baked; the
entrypoint is `vast/onstart.sh`.

- [ ] **Step 2: Create the Dockerfile**

Create `services/local_worker/vast/Dockerfile`:

```dockerfile
# Baked private image for vast.ai bulk analysis. NOT for public registry
# (TensorRT operator tarball is baked; keep registry private).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ARG WORKER_VERSION=0.9.7
ARG BT4_URL=https://storage.lczero.org/files/networks-contrib/BT4-1024x15x32h-swa-6147500.pb.gz
ARG LC0_URL
ARG WLW_TRT_URL
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3.11 python3-pip stockfish curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# lc0 (TRT build) — baked, not volume-fetched.
RUN curl -fsSL "${LC0_URL}" -o /tmp/lc0.tar.gz \
    && mkdir -p /opt/lc0 && tar -xzf /tmp/lc0.tar.gz -C /opt/lc0 \
    && rm /tmp/lc0.tar.gz

# TensorRT libraries (operator tarball; baked because registry is private).
RUN if [ -n "${WLW_TRT_URL}" ]; then \
      curl -fsSL "${WLW_TRT_URL}" -o /tmp/trt.tar.gz \
      && mkdir -p /opt/trt && tar -xzf /tmp/trt.tar.gz -C /opt/trt \
      && rm /tmp/trt.tar.gz ; fi

# BT4 weights + Syzygy 3-4-5 — baked.
RUN mkdir -p /opt/weights /opt/syzygy \
    && curl -fsSL "${BT4_URL}" -o /opt/weights/BT4.pb.gz
RUN for t in $(curl -fsSL https://tablebase.sesse.net/syzygy/3-4-5/ \
      | grep -oE '[A-Za-z0-9_]+\.(rtbw|rtbz)' | sort -u); do \
      curl -fsSL "https://tablebase.sesse.net/syzygy/3-4-5/$t" -o "/opt/syzygy/$t"; \
    done

RUN python3.11 -m pip install --no-cache-dir "wood-league-worker==${WORKER_VERSION}"

COPY vast/onstart.sh /usr/local/bin/wlw-vast-onstart
RUN chmod +x /usr/local/bin/wlw-vast-onstart

# Worker asset paths point at the in-image bake locations.
ENV WLW_LC0_PATH=/opt/lc0/lc0 \
    WLW_LC0_WEIGHTS_PATH=/opt/weights/BT4.pb.gz \
    WLW_SYZYGY_PATH=/opt/syzygy \
    WLW_STOCKFISH_PATH=/usr/games/stockfish \
    WLW_LC0_BACKEND=trt \
    LD_LIBRARY_PATH=/opt/trt/lib:${LD_LIBRARY_PATH:-} \
    WLW_DATA_DIR=/data/wlw

ENTRYPOINT ["/usr/local/bin/wlw-vast-onstart"]
```

- [ ] **Step 3: Build the image locally (no GPU needed to build)**

Run from `services/local_worker`:
`docker build -f vast/Dockerfile --build-arg LC0_URL=<lc0-trt-tarball-url> --build-arg WLW_TRT_URL=<operator-trt-url> -t wl-vast-worker:dev .`
Expected: build succeeds; `docker run --rm --entrypoint sh wl-vast-worker:dev -c 'ls /opt/lc0 /opt/weights /opt/syzygy && wood-league-worker --help'`
shows the baked assets and the worker CLI.

- [ ] **Step 4: Commit**

```bash
git add services/local_worker/vast/Dockerfile
git commit -m "feat(vast): baked private worker image (lc0+TRT, weights, syzygy)"
```

---

## Task 11: Operator launch recipe (README)

**Files:**
- Create: `services/local_worker/vast/README.md`

- [ ] **Step 1: Write the operator doc**

Create `services/local_worker/vast/README.md` with: the private-registry
push/auth one-time setup; the parameterized `vastai create instance`
command (from the spec's Launch surface section); the full env contract
table (`WLW_MAX_JOBS`, `WL_CAMPAIGN_ID`, `WL_INSTANCE_ID`,
`WL_SKIP_CACHE_PULL`, `WL_CACHE_CHECKPOINT_MINUTES`, `WLW_BATCH_TIME`,
bucket creds `RAILWAY_BUCKET_NAME`/`ENDPOINT`/`REGION`/`ACCESS_KEY_ID`/`SECRET_ACCESS_KEY`);
the **offer filter** guidance (minimum vCPU for the lc0+Stockfish thread
split, minimum RAM for both engines + NN + Syzygy resident — open items
O5/O4 in the spec); the micro-batch example (`WLW_MAX_JOBS=20`); and the
between-campaigns manual merge command:
`wood-league-worker cache-merge --canonical canonical.sqlite --delta <each-downloaded-delta> --max-mb 500`.

- [ ] **Step 2: Commit**

```bash
git add services/local_worker/vast/README.md
git commit -m "docs(vast): operator launch recipe + env contract + merge runbook"
```

---

## Task 12: CI — build & push the private image

**Files:**
- Create: `.github/workflows/build-vast-worker.yml`

- [ ] **Step 1: Inspect the existing image-build workflow**

Open `.github/workflows/build-lc0-worker.yml` and mirror its structure
(checkout, buildx, registry login, build+push). Differences: build context
`services/local_worker`, dockerfile `services/local_worker/vast/Dockerfile`,
push to the **private** registry repo, pass `LC0_URL` / `WLW_TRT_URL` /
`WORKER_VERSION` build args from repo secrets.

- [ ] **Step 2: Create the workflow**

Create `.github/workflows/build-vast-worker.yml`:

```yaml
name: build-vast-worker
on:
  push:
    tags: ["vast-worker-v*"]
  workflow_dispatch:
    inputs:
      worker_version:
        description: "wood-league-worker PyPI version to bake"
        required: true
jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: services/local_worker
          file: services/local_worker/vast/Dockerfile
          push: true
          tags: ghcr.io/${{ github.repository }}/vast-worker:${{ github.event.inputs.worker_version || github.ref_name }}
          build-args: |
            WORKER_VERSION=${{ github.event.inputs.worker_version || '0.9.7' }}
            LC0_URL=${{ secrets.LC0_TRT_TARBALL_URL }}
            WLW_TRT_URL=${{ secrets.WLW_TRT_URL }}
```

> The GHCR package must be set to **private** in repo settings (the spec
> requires a private registry because the TRT tarball is baked).

- [ ] **Step 3: Validate the workflow YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/build-vast-worker.yml')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/build-vast-worker.yml
git commit -m "ci(vast): build & push baked private worker image"
```

---

## Verification (end-to-end)

1. **Unit/regression:** `cd services/local_worker && source ../../.venv/bin/activate && python -m pytest -q` — all pass (existing + new).
2. **Quality gate:** the 5-stage pipeline clean on all new/changed files (Task 8).
3. **Image:** CI produces a private `ghcr.io/<repo>/vast-worker:<ver>` image; `docker run` shows baked `/opt/lc0`, `/opt/weights`, `/opt/syzygy` and a working `wood-league-worker --help`.
4. **Cache round-trip (no GPU needed):** with the Railway bucket env vars set, run a tiny script that calls `make_s3_client` → seed a small `eval_cache.sqlite` → `upload_delta` → delete local → `pull_canonical` → confirm rows present; then `wood-league-worker cache-merge` two deltas and confirm union + last-writer-wins.
5. **Live micro batch (after E lands):** `vastai create instance <offer> --image <private>/vast-worker:<ver> --env '-e WLW_MAX_JOBS=20 -e WL_CAMPAIGN_ID=micro-$(date +%Y%m%d) -e <bucket creds>' --onstart wlw-vast-onstart --ssh`. Confirm: both engines active concurrently in logs (GPU not idle behind Stockfish), both processes exit after their cap, a delta object appears under `eval_cache/checkpoints/<campaign>/`, instance ends.
6. **Compounding:** run the manual `cache-merge` on the campaign's deltas → publish as canonical → a fresh boot shows cache hit-rate > 0 (issue-#85 sampling).

## Self-Review Notes

- **Spec coverage:** baked image (Task 10), boot-time-pull fail-soft (Task 4, Task 9), `WL_SKIP_CACHE_PULL` (Task 9), periodic + on-exit per-instance checkpoint with no live merge (Task 5, Task 9), WAL-safe snapshot (Task 2), offline manual merge + prune + vacuum (Task 6, Task 7), concurrent dual-engine via two processes mirroring proven RunPod pattern (Task 9), `WLW_MAX_JOBS`/E as sequenced prerequisite (Prerequisites + Task 9 note), launch surface + offer filters + O4/O5 surfaced to operator (Task 11), private-registry CI (Task 12). E itself is intentionally out of scope (separate spec/plan) — flagged, not silently bundled.
- **No placeholders:** every code/script/yaml step contains complete content.
- **Type/name consistency:** `make_s3_client`, `pull_canonical`, `upload_delta`, `snapshot_db`, `checkpoint_key`, `CANONICAL_KEY`, `merge_deltas` are defined once and used with identical signatures across tasks, the CLI command, and the entrypoint.
