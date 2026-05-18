# lc0 Cold-Start Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the ~7.5-minute per-instance lc0 calibration sweep by baking a known-good calibration into the vast image (Phase 1) and persisting it to the object-storage bucket keyed by fingerprint (Phase 2).

**Architecture:** A new fail-soft sync module mirrors `cache_sync.py`. `lc0_tuning.py` gains a single optional `on_calibrated` callback; the lc0 analysis call site wires it to a fail-soft S3 push. Boot pull is a new CLI subcommand invoked from `onstart.sh` exactly like `plan-sf-fanout`. Phase 1 commits a real captured `lc0_tuning.json` and `COPY`s it into the image with a build-time structural guard.

**Tech Stack:** Python 3.11 (`wood-league-worker` package), `typer` CLI, `boto3` S3, `pytest`, Docker (vast image).

**Spec:** `docs/superpowers/specs/2026-05-17-lc0-cold-start-cache-design.md` (issue #150, branch `issue/150-lc0-cold-start-cache`).

**Key facts established during planning (do not re-derive):**
- Runtime fingerprint is `{"gpu":"", "lc0_version":"", "weights":"BT4.pb.gz", "backend":"onnx-trt"}` because `lc0.py:506` calls `get_tuned_opts(..., gpu_name="", lc0_version="")` and the image sets `WLW_LC0_WEIGHTS_PATH=/opt/weights/BT4.pb.gz`, `WLW_LC0_BACKEND=onnx-trt`. `compute_fingerprint` stores `Path(weights_path).name`.
- **Known limitation (out of scope, document only):** because `gpu_name`/`lc0_version` are passed empty, the fingerprint ignores GPU model and lc0 version; Phase 2 self-heals on weights/backend change only. Not fixed here.
- Runtime `data_dir()` = `/data/wlw` (image `ENV WLW_DATA_DIR=/data/wlw`, re-defaulted in `onstart.sh`). `cache_path()` = `/data/wlw/lc0_tuning.json`. No host volume shadows it (onstart: "No host volume").
- `lc0_tuning.py` already imports `Callable, Optional` from `typing` — no new import needed for the callback.
- All worker tests run from `services/local_worker/`. Activate the repo venv: `source /Users/christopherwebster/Projects/wood_league/.venv/bin/activate`.

---

## File Structure

- **Create** `services/local_worker/local_worker/lc0_tuning_sync.py` — fingerprint→key, fail-soft pull/push, env-gated auto-push helper. One responsibility: object-storage transport for the tuning JSON.
- **Create** `services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py` — `lc0-tuning-pull` CLI command (boot-time pull, mirrors `plan_sf_fanout_cmd.py`).
- **Create** `services/local_worker/tests/test_lc0_tuning_sync.py` — unit tests (mirror `tests/test_cache_sync.py`).
- **Create** `services/local_worker/tests/test_lc0_tuning_pull_cmd.py` — CLI command unit tests.
- **Create** `services/local_worker/vast/lc0_tuning.l40s.json` — captured real calibration (Task 6, piggyback).
- **Create** `services/local_worker/tests/test_baked_lc0_tuning.py` — structural guard for the committed JSON.
- **Modify** `services/local_worker/local_worker/analysis/lc0_tuning.py` — add `on_calibrated` param + post-`save_cache` call (one edit region).
- **Modify** `services/local_worker/local_worker/analysis/lc0.py:506` — wire `on_calibrated` + import.
- **Modify** `services/local_worker/local_worker/cli.py` — register `lc0-tuning-pull`.
- **Modify** `services/local_worker/vast/onstart.sh` — invoke `lc0-tuning-pull` after `pull_cache`.
- **Modify** `services/local_worker/vast/Dockerfile` — `COPY` baked JSON + build guard.
- **Modify** `services/local_worker/pyproject.toml` — version bump 0.9.14 → 0.9.15.

---

## Task 1: `lc0_tuning_sync` — fingerprint→key + fail-soft pull/push

**Files:**
- Create: `services/local_worker/local_worker/lc0_tuning_sync.py`
- Test: `services/local_worker/tests/test_lc0_tuning_sync.py`

- [ ] **Step 1: Write the failing tests**

Create `services/local_worker/tests/test_lc0_tuning_sync.py`:

```python
"""
Title: test_lc0_tuning_sync.py — Tests for lc0 tuning-cache object sync
Description:
    Unit tests (no live S3) for lc0_tuning_sync: per-fingerprint object
    key, fail-soft pull, fail-soft push. Mirrors test_cache_sync.py.
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
import json
from pathlib import Path

import local_worker.lc0_tuning_sync as ts

_FP = {"gpu": "", "lc0_version": "", "weights": "BT4.pb.gz", "backend": "onnx-trt"}
_FP2 = {"gpu": "", "lc0_version": "", "weights": "BT4.pb.gz", "backend": "cuda-fp16"}


def test_object_key_is_stable_and_namespaced():
    k1 = ts.tuning_object_key(_FP)
    k2 = ts.tuning_object_key(dict(reversed(list(_FP.items()))))
    assert k1 == k2  # key independent of dict ordering
    assert k1.startswith("lc0_tuning/")
    assert k1.endswith(".json")


def test_object_key_differs_when_any_field_differs():
    assert ts.tuning_object_key(_FP) != ts.tuning_object_key(_FP2)


class _PullClient:
    def __init__(self, *, raise_on_download=False):
        self.raise_on_download = raise_on_download
        self.downloaded = None

    def download_file(self, bucket, key, dest):
        if self.raise_on_download:
            raise RuntimeError("no such key")
        self.downloaded = (bucket, key, dest)
        Path(dest).write_text(json.dumps({"fingerprint": _FP}))


def test_pull_tuning_writes_file_on_success(tmp_path):
    client = _PullClient()
    dest = tmp_path / "lc0_tuning.json"
    ok = ts.pull_tuning(client, "wl-bucket", _FP, dest)
    assert ok is True
    assert json.loads(dest.read_text())["fingerprint"] == _FP
    assert client.downloaded == ("wl-bucket", ts.tuning_object_key(_FP), str(dest))


def test_pull_tuning_failsoft_on_missing(tmp_path):
    client = _PullClient(raise_on_download=True)
    dest = tmp_path / "lc0_tuning.json"
    ok = ts.pull_tuning(client, "wl-bucket", _FP, dest)
    assert ok is False           # never raises
    assert not dest.exists()     # no partial file left behind


class _PushClient:
    def __init__(self, *, raise_on_upload=False):
        self.raise_on_upload = raise_on_upload
        self.uploaded = None

    def upload_file(self, src, bucket, key):
        if self.raise_on_upload:
            raise RuntimeError("network down")
        self.uploaded = (src, bucket, key)


def test_push_tuning_keys_by_embedded_fingerprint(tmp_path):
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP, "minibatch_size": 256}))
    client = _PushClient()
    ts.push_tuning(client, "wl-bucket", cache)
    src, bucket, key = client.uploaded
    assert bucket == "wl-bucket"
    assert key == ts.tuning_object_key(_FP)
    assert src == str(cache)


def test_push_tuning_failsoft_when_cache_absent(tmp_path):
    client = _PushClient()
    ts.push_tuning(client, "wl-bucket", tmp_path / "missing.json")
    assert client.uploaded is None  # nothing uploaded, no exception


def test_push_tuning_failsoft_on_upload_error(tmp_path):
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP}))
    client = _PushClient(raise_on_upload=True)
    ts.push_tuning(client, "wl-bucket", cache)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning_sync.py -p no:cacheprovider -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'local_worker.lc0_tuning_sync'`

- [ ] **Step 3: Write minimal implementation**

Create `services/local_worker/local_worker/lc0_tuning_sync.py`:

```python
"""
Title: lc0_tuning_sync.py — Persist the lc0 calibration cache to object storage
Description:
    The lc0 MinibatchSize calibration (~7.5 min `lc0 benchmark` sweep)
    is cached in lc0_tuning.json in the worker data dir, which is
    ephemeral on vast.ai — every fresh instance starts cold and pays
    the sweep. This module persists that JSON to the Railway-compatible
    bucket, keyed by a hash of its fingerprint so different
    weights/backends never clobber one another (the on-disk cache is
    single-entry). Fail-soft throughout, exactly like cache_sync.py: an
    object-storage failure must never interrupt analysis — the worker
    just recalibrates as it does today (issue #150).
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from local_worker.cache_sync import make_s3_client

log = logging.getLogger(__name__)

_KEY_PREFIX = "lc0_tuning"


def tuning_object_key(fingerprint: dict) -> str:
    """Object key for a calibration fingerprint.

    Args:
        fingerprint: The compute_fingerprint() dict
            (gpu, lc0_version, weights, backend).

    Returns:
        ``lc0_tuning/<sha1>.json`` — deterministic and independent of
        dict key ordering, so each GPU/version/weights/backend combo
        gets its own object and none clobbers another.
    """
    canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()  # noqa: S324 — non-crypto cache key
    return f"{_KEY_PREFIX}/{digest}.json"


def pull_tuning(
    client: Any, bucket: str, fingerprint: dict, dest: Path
) -> bool:
    """Download this fingerprint's calibration JSON to ``dest``. Never raises.

    Args:
        client: S3 client exposing ``download_file(bucket, key, dest)``.
        bucket: Bucket name.
        fingerprint: Current host fingerprint (selects the object key).
        dest: Local path to write the calibration JSON to
            (typically ``cache_path()``).

    Returns:
        True if the object was fetched, False otherwise. A partially
        written file is removed on failure so a corrupt cache can never
        be read back.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = tuning_object_key(fingerprint)
    try:
        client.download_file(bucket, key, str(dest))
        return True
    except Exception as exc:  # noqa: BLE001 — fail-soft is the contract
        log.warning(
            "lc0_tuning_sync: pull %s failed (%s); will calibrate", key, exc
        )
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


def push_tuning(client: Any, bucket: str, cache_path: Path) -> None:
    """Upload the freshly written calibration JSON. Never raises.

    The object key is derived from the *embedded* fingerprint in the
    file itself, so the file always lands under the key a future
    pull_tuning() will look for.

    Args:
        client: S3 client exposing ``upload_file(src, bucket, key)``.
        bucket: Bucket name.
        cache_path: Path to the just-written lc0_tuning.json.
    """
    if not cache_path.exists():
        log.info("lc0_tuning_sync: no calibration file to push; skipping")
        return
    try:
        payload = json.loads(cache_path.read_text())
        fingerprint = payload["fingerprint"]
        client.upload_file(
            str(cache_path), bucket, tuning_object_key(fingerprint)
        )
    except Exception as exc:  # noqa: BLE001 — push must not break the run
        log.warning("lc0_tuning_sync: push failed (%s); ignored", exc)


def push_after_calibrate(cache_path: Path) -> None:
    """Env-gated, fail-soft auto-push hook for get_tuned_opts(on_calibrated=).

    Builds an S3 client from env and pushes. A no-op (logged) when no
    bucket is configured (e.g. local dev / non-vast), so wiring this
    into the analysis path is safe everywhere.

    Args:
        cache_path: Path to the just-written lc0_tuning.json.
    """
    if not os.environ.get("RAILWAY_BUCKET_NAME"):
        log.info("lc0_tuning_sync: no bucket configured; skip calibration push")
        return
    try:
        client, bucket = make_s3_client()
    except Exception as exc:  # noqa: BLE001 — never break analysis
        log.warning("lc0_tuning_sync: S3 client init failed (%s); ignored", exc)
        return
    push_tuning(client, bucket, cache_path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning_sync.py -p no:cacheprovider -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
ruff check services/local_worker/local_worker/lc0_tuning_sync.py services/local_worker/tests/test_lc0_tuning_sync.py
bandit -ll -q services/local_worker/local_worker/lc0_tuning_sync.py
git add services/local_worker/local_worker/lc0_tuning_sync.py services/local_worker/tests/test_lc0_tuning_sync.py
git commit -m "feat(worker): lc0_tuning_sync — fingerprint-keyed fail-soft S3 pull/push (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
Expected: ruff "All checks passed!", bandit no Medium/High.

---

## Task 2: `lc0_tuning.get_tuned_opts` — optional `on_calibrated` callback

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0_tuning.py` (signature ~428-437; call after `save_cache` ~480-489)
- Test: `services/local_worker/tests/test_lc0_tuning.py` (existing file — append)

- [ ] **Step 1: Write the failing tests**

Append to `services/local_worker/tests/test_lc0_tuning.py`:

```python
def test_on_calibrated_fires_once_on_cache_miss(tmp_path):
    """on_calibrated is invoked with the cache path exactly once when a
    calibration is freshly computed (cache miss)."""
    from local_worker.analysis import lc0_tuning

    calls = []
    cache_file = tmp_path / "lc0_tuning.json"

    def fake_runner(cmd):
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, stdout="1000 nps\n", stderr="")

    lc0_tuning.get_tuned_opts(
        lc0_path="/bin/sh",  # exists → calibration not skipped
        weights_path="/w/BT4.pb.gz",
        backend="onnx-trt",
        gpu_name="",
        lc0_version="",
        cache_file=cache_file,
        runner=fake_runner,
        on_calibrated=calls.append,
    )

    assert calls == [cache_file]


def test_on_calibrated_not_fired_on_cache_hit(tmp_path):
    """A pre-populated, fingerprint-matching cache must not recalibrate,
    so on_calibrated must not fire."""
    import json
    from local_worker.analysis import lc0_tuning

    cache_file = tmp_path / "lc0_tuning.json"
    fp = lc0_tuning.compute_fingerprint("", "", "/w/BT4.pb.gz", "onnx-trt")
    cache_file.write_text(json.dumps({
        "fingerprint": fp, "minibatch_size": 256, "max_prefetch": 32,
        "measured_nps": 1.0, "calibrated_at": "x",
    }))

    calls = []
    lc0_tuning.get_tuned_opts(
        lc0_path="/bin/sh", weights_path="/w/BT4.pb.gz", backend="onnx-trt",
        gpu_name="", lc0_version="", cache_file=cache_file,
        on_calibrated=calls.append,
    )
    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning.py -k on_calibrated -p no:cacheprovider -q`
Expected: FAIL with `TypeError: get_tuned_opts() got an unexpected keyword argument 'on_calibrated'`

- [ ] **Step 3: Implement the minimal change**

In `services/local_worker/local_worker/analysis/lc0_tuning.py`, edit the `get_tuned_opts` signature (add the param before the closing `)` of the keyword-only args, after `force_recalibrate`):

```python
def get_tuned_opts(
    *,
    lc0_path: str,
    weights_path: str,
    backend: str,
    gpu_name: str,
    lc0_version: str,
    cache_file: Optional[Path] = None,
    runner: Optional[BenchmarkRunner] = None,
    force_recalibrate: bool = False,
    on_calibrated: Optional[Callable[[Path], None]] = None,
) -> dict[str, str]:
```

Add to the docstring `Args:` block (after the `force_recalibrate:` line):

```python
        on_calibrated: Optional callback invoked with the cache file
            path immediately after a *fresh* calibration is persisted
            (cache miss only). Used to push the result to durable
            storage; never called on a cache hit. Default None (no-op).
```

Replace the existing `save_cache(...)` block (currently the final statements of the function, lines ~480-490) with the same call followed by the callback:

```python
    target_cache = cache_file or cache_path()
    save_cache(
        {
            "fingerprint": fingerprint,
            "minibatch_size": calibration["minibatch_size"],
            "max_prefetch": calibration["max_prefetch"],
            "measured_nps": calibration["measured_nps"],
            "calibrated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        target_cache,
    )
    if on_calibrated is not None:
        try:
            on_calibrated(target_cache)
        except Exception:  # noqa: BLE001 — callback must never break tuning
            log.warning("lc0_tuning: on_calibrated callback raised; ignored")
    return opts
```

(`Callable` and `Optional` are already imported at line 42 — verify, add nothing.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning.py -p no:cacheprovider -q`
Expected: PASS (all existing lc0_tuning tests + 2 new). The default-`None` path is exercised by every pre-existing test → regression guard for the edit.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
ruff check services/local_worker/local_worker/analysis/lc0_tuning.py services/local_worker/tests/test_lc0_tuning.py
bandit -ll -q services/local_worker/local_worker/analysis/lc0_tuning.py
git add services/local_worker/local_worker/analysis/lc0_tuning.py services/local_worker/tests/test_lc0_tuning.py
git commit -m "feat(worker): get_tuned_opts on_calibrated hook (cache-miss only) (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wire the auto-push at the lc0 analysis call site

**Files:**
- Modify: `services/local_worker/local_worker/analysis/lc0.py` (import near line 47; call at line 506-512)
- Test: `services/local_worker/tests/test_lc0.py` (existing file — append; if absent, create with the header below)

- [ ] **Step 1: Write the failing test**

Append to `services/local_worker/tests/test_lc0.py` (create the file with this docstring header if it does not exist — `"""Title: test_lc0.py — lc0 analysis wiring tests\nChangelog:\n    2026-05-17: on_calibrated push wiring (#150).\n"""`):

```python
def test_merge_tuned_opts_passes_push_hook(monkeypatch):
    """_merge_tuned_opts must hand get_tuned_opts the push_after_calibrate
    hook so a fresh calibration is persisted to the bucket."""
    from local_worker.analysis import lc0

    seen = {}

    def fake_get_tuned_opts(**kwargs):
        seen["on_calibrated"] = kwargs.get("on_calibrated")
        return {}

    monkeypatch.setattr(lc0, "get_tuned_opts", fake_get_tuned_opts)

    lc0._merge_tuned_opts(
        {}, lc0_path="/opt/lc0/lc0", weights_path="/opt/weights/BT4.pb.gz",
        backend="onnx-trt",
    )

    from local_worker.lc0_tuning_sync import push_after_calibrate
    assert seen["on_calibrated"] is push_after_calibrate
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/local_worker && python -m pytest tests/test_lc0.py -k push_hook -p no:cacheprovider -q`
Expected: FAIL — `on_calibrated` is `None` (assertion error).

- [ ] **Step 3: Implement the wiring**

In `services/local_worker/local_worker/analysis/lc0.py`, add an import next to the existing tuning import (line ~47, immediately after `from .lc0_tuning import get_tuned_opts`):

```python
from ..lc0_tuning_sync import push_after_calibrate
```

In `_merge_tuned_opts`, change the `get_tuned_opts(...)` call (lines 506-512) to pass the hook:

```python
    tuned = get_tuned_opts(
        lc0_path=lc0_path,
        weights_path=weights_path,
        backend=backend,
        gpu_name="",
        lc0_version="",
        on_calibrated=push_after_calibrate,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/local_worker && python -m pytest tests/test_lc0.py -k push_hook -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
ruff check services/local_worker/local_worker/analysis/lc0.py services/local_worker/tests/test_lc0.py
bandit -ll -q services/local_worker/local_worker/analysis/lc0.py
git add services/local_worker/local_worker/analysis/lc0.py services/local_worker/tests/test_lc0.py
git commit -m "feat(worker): push lc0 calibration to bucket after a fresh sweep (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `lc0-tuning-pull` CLI command (boot-time pull)

**Files:**
- Create: `services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py`
- Modify: `services/local_worker/local_worker/cli.py` (import block ~37; registration block ~145)
- Test: `services/local_worker/tests/test_lc0_tuning_pull_cmd.py`

- [ ] **Step 1: Write the failing tests**

Create `services/local_worker/tests/test_lc0_tuning_pull_cmd.py`:

```python
"""
Title: test_lc0_tuning_pull_cmd.py — Tests for the lc0-tuning-pull command
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
from pathlib import Path

import local_worker.commands.lc0_tuning_pull_cmd as cmd


def test_fingerprint_from_env_mirrors_lc0_call(monkeypatch):
    """Fingerprint must match lc0.py's get_tuned_opts call exactly:
    gpu/lc0_version empty, weights basename, backend from env."""
    monkeypatch.setenv("WLW_LC0_WEIGHTS_PATH", "/opt/weights/BT4.pb.gz")
    monkeypatch.setenv("WLW_LC0_BACKEND", "onnx-trt")
    assert cmd._fingerprint_from_env() == {
        "gpu": "", "lc0_version": "", "weights": "BT4.pb.gz",
        "backend": "onnx-trt",
    }


def test_lc0_tuning_pull_failsoft_without_bucket(monkeypatch, capsys):
    """No bucket env → command prints a skip line and exits 0
    (never raises, never blocks boot)."""
    monkeypatch.delenv("RAILWAY_BUCKET_NAME", raising=False)
    cmd.lc0_tuning_pull()  # must not raise
    assert "skip" in capsys.readouterr().out.lower()


def test_lc0_tuning_pull_invokes_pull_to_cache_path(monkeypatch, tmp_path):
    """With a bucket configured, it pulls using the env fingerprint into
    cache_path()."""
    monkeypatch.setenv("WLW_LC0_WEIGHTS_PATH", "/opt/weights/BT4.pb.gz")
    monkeypatch.setenv("WLW_LC0_BACKEND", "onnx-trt")
    monkeypatch.setenv("RAILWAY_BUCKET_NAME", "wl-bucket")

    dest = tmp_path / "lc0_tuning.json"
    monkeypatch.setattr(cmd, "cache_path", lambda: dest)
    monkeypatch.setattr(cmd, "make_s3_client", lambda: ("CLIENT", "wl-bucket"))

    seen = {}

    def fake_pull(client, bucket, fingerprint, d):
        seen.update(client=client, bucket=bucket, fp=fingerprint, dest=d)
        return True

    monkeypatch.setattr(cmd, "pull_tuning", fake_pull)
    cmd.lc0_tuning_pull()

    assert seen["client"] == "CLIENT"
    assert seen["bucket"] == "wl-bucket"
    assert seen["fp"]["weights"] == "BT4.pb.gz"
    assert seen["dest"] == dest
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning_pull_cmd.py -p no:cacheprovider -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'local_worker.commands.lc0_tuning_pull_cmd'`

- [ ] **Step 3: Write the command**

Create `services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py`:

```python
"""
Title: lc0_tuning_pull_cmd.py — `lc0-tuning-pull` CLI command
Description:
    Invoked from onstart.sh at instance boot (mirrors `plan-sf-fanout`).
    Reconstructs the lc0 calibration fingerprint from the worker's
    image env (exactly as lc0.py's get_tuned_opts call does:
    gpu/lc0_version empty, weights basename, backend from env), then
    fail-soft pulls that fingerprint's cached calibration from the
    bucket into cache_path(). A hit means the next analysis run skips
    the ~7.5-minute MinibatchSize sweep entirely (issue #150).
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
from __future__ import annotations

import os
from pathlib import Path

import typer

from local_worker.analysis.lc0_tuning import cache_path, compute_fingerprint
from local_worker.cache_sync import make_s3_client
from local_worker.lc0_tuning_sync import pull_tuning


def _fingerprint_from_env() -> dict:
    """Build the calibration fingerprint from image env vars.

    Mirrors local_worker.analysis.lc0._merge_tuned_opts: gpu_name and
    lc0_version are empty (that is how get_tuned_opts is called), so the
    fingerprint depends only on the weights basename and backend.

    Returns:
        The compute_fingerprint() dict for the current image config.
    """
    return compute_fingerprint(
        "",  # gpu_name — empty, mirrors lc0.py
        "",  # lc0_version — empty, mirrors lc0.py
        os.environ.get("WLW_LC0_WEIGHTS_PATH", ""),
        os.environ.get("WLW_LC0_BACKEND", ""),
    )


def lc0_tuning_pull() -> None:
    """Fail-soft boot pull of this fingerprint's calibration cache."""
    if not os.environ.get("RAILWAY_BUCKET_NAME"):
        typer.echo("lc0-tuning-pull: no bucket configured; skip")
        return
    fingerprint = _fingerprint_from_env()
    try:
        client, bucket = make_s3_client()
    except Exception as exc:  # noqa: BLE001 — boot must not fail
        typer.echo(f"lc0-tuning-pull: S3 init failed ({exc}); will calibrate")
        return
    dest: Path = cache_path()
    ok = pull_tuning(client, bucket, fingerprint, dest)
    typer.echo(
        "lc0-tuning-pull: cache hit (sweep skipped)"
        if ok
        else "lc0-tuning-pull: miss; worker will calibrate once"
    )
```

In `services/local_worker/local_worker/cli.py`, add to the command-imports block (alphabetical-ish, next to the other `from local_worker.commands import ...` lines near line 37):

```python
from local_worker.commands import lc0_tuning_pull_cmd
```

And in the registration block (near line 145, next to `app.command("plan-sf-fanout")(...)`):

```python
app.command("lc0-tuning-pull")(lc0_tuning_pull_cmd.lc0_tuning_pull)
```

- [ ] **Step 4: Run tests + smoke the CLI**

Run: `cd services/local_worker && python -m pytest tests/test_lc0_tuning_pull_cmd.py -p no:cacheprovider -q`
Expected: PASS (3 passed)

Run: `cd services/local_worker && python -m local_worker.cli lc0-tuning-pull`
Expected: prints `lc0-tuning-pull: no bucket configured; skip`, exit 0.

- [ ] **Step 5: Lint + commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
ruff check services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py services/local_worker/local_worker/cli.py services/local_worker/tests/test_lc0_tuning_pull_cmd.py
bandit -ll -q services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py
git add services/local_worker/local_worker/commands/lc0_tuning_pull_cmd.py services/local_worker/local_worker/cli.py services/local_worker/tests/test_lc0_tuning_pull_cmd.py
git commit -m "feat(worker): lc0-tuning-pull CLI — boot-time fail-soft calibration pull (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Invoke `lc0-tuning-pull` from `onstart.sh`

**Files:**
- Modify: `services/local_worker/vast/onstart.sh` (after `pull_cache` at line 60)

- [ ] **Step 1: Add the boot-pull call**

In `services/local_worker/vast/onstart.sh`, immediately after the `pull_cache` invocation (currently line 60, the standalone `pull_cache`) and before the `# --- compute Stockfish fan-out` comment (line 62), insert:

```bash
# Pull this image's lc0 calibration (fail-soft; never blocks boot). A
# hit lets the lc0 worker skip the ~7.5-min MinibatchSize sweep (#150).
if [ "${WL_SKIP_LC0_TUNING_PULL:-0}" = "1" ]; then
  echo "onstart: WL_SKIP_LC0_TUNING_PULL=1, skipping lc0 calibration pull"
else
  wood-league-worker lc0-tuning-pull || true
fi
```

- [ ] **Step 2: Lint the script**

Run: `bash -n services/local_worker/vast/onstart.sh && shellcheck services/local_worker/vast/onstart.sh || true`
Expected: `bash -n` exits 0 (no syntax error). shellcheck warnings (if any) reviewed; none introduced by the added block (it mirrors the existing `pull_cache` guard idiom).

- [ ] **Step 3: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/local_worker/vast/onstart.sh
git commit -m "feat(vast): onstart pulls lc0 calibration cache before launch (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Phase 1 — capture, commit, and bake the L40S calibration JSON

> **Sequencing note:** This task's *capture* step (6.1) is gated on the next sea-trial supplying a real `lc0_tuning.json` (zero extra spend — piggyback, per the spec). Steps 6.2–6.5 (Dockerfile + guard + test) can be written before capture using a committed placeholder ONLY if the structural test is calibrated to the real file afterward. **Do capture first if a trial is imminent.**

**Files:**
- Create: `services/local_worker/vast/lc0_tuning.l40s.json`
- Create: `services/local_worker/tests/test_baked_lc0_tuning.py`
- Modify: `services/local_worker/vast/Dockerfile`

- [ ] **Step 1: Capture the real calibration from a sea-trial instance**

Before the trial instance is destroyed, with its `<id>` from `vastai show instances`:

```bash
vastai execute <id> "cat /data/wlw/lc0_tuning.json"
```

Save the printed JSON verbatim to `services/local_worker/vast/lc0_tuning.l40s.json`. It must contain `fingerprint`, `minibatch_size`, `max_prefetch`, `measured_nps`, `calibrated_at`. Confirm `fingerprint.backend` is non-empty and `fingerprint.weights == "BT4.pb.gz"` (sanity vs. the image config). Do **not** hand-edit values — commit exactly what the worker wrote.

- [ ] **Step 2: Write the structural guard test**

Create `services/local_worker/tests/test_baked_lc0_tuning.py`:

```python
"""
Title: test_baked_lc0_tuning.py — Structural guard for the baked L40S calibration
Description:
    vast/lc0_tuning.l40s.json is COPYd into the image at the data-dir
    path so a fresh instance is a calibration cache hit (skips the
    ~7.5-min sweep). This guards the committed artifact's shape — a
    malformed or empty bake silently degrades to a full sweep, which is
    exactly the cost we are removing (issue #150).
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
import json
from pathlib import Path

_BAKED = (
    Path(__file__).resolve().parent.parent / "vast" / "lc0_tuning.l40s.json"
)


def test_baked_calibration_is_well_formed():
    data = json.loads(_BAKED.read_text())
    fp = data["fingerprint"]
    assert set(fp) == {"gpu", "lc0_version", "weights", "backend"}
    assert fp["weights"] == "BT4.pb.gz"   # matches image WLW_LC0_WEIGHTS_PATH
    assert fp["backend"]                  # non-empty backend
    assert isinstance(data["minibatch_size"], int) and data["minibatch_size"] >= 1
    assert isinstance(data["max_prefetch"], int) and data["max_prefetch"] >= 0
    assert float(data["measured_nps"]) > 0
```

- [ ] **Step 3: Run the guard test**

Run: `cd services/local_worker && python -m pytest tests/test_baked_lc0_tuning.py -p no:cacheprovider -q`
Expected: PASS. (If it fails, the captured JSON is wrong — re-capture; do not weaken the test.)

- [ ] **Step 4: Bake it into the image with a build guard**

In `services/local_worker/vast/Dockerfile`, after the `RUN python3.11 -m pip install ... wood-league-worker==${WORKER_VERSION}` line (line 59) and before the `COPY vast/onstart.sh` line (line 61), insert:

```dockerfile
# Bake a known-good L40S lc0 calibration so a fresh instance is a cache
# hit and skips the ~7.5-min MinibatchSize sweep (#150). Build-time
# guard (same philosophy as the TRT/Syzygy/WORKER_VERSION guards): fail
# the BUILD if the bake is missing or malformed rather than discover a
# silent full-sweep regression after a paid launch.
COPY vast/lc0_tuning.l40s.json /data/wlw/lc0_tuning.json
RUN python3.11 - <<'PY'
import json, sys
d = json.load(open("/data/wlw/lc0_tuning.json"))
fp = d["fingerprint"]
ok = bool(fp.get("backend")) and fp.get("weights") == "BT4.pb.gz" \
     and isinstance(d.get("minibatch_size"), int) and d["minibatch_size"] >= 1
sys.exit(0 if ok else "FATAL: baked lc0_tuning.json malformed (#150)")
PY
```

- [ ] **Step 5: Commit**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/local_worker/vast/lc0_tuning.l40s.json services/local_worker/tests/test_baked_lc0_tuning.py services/local_worker/vast/Dockerfile
git commit -m "feat(vast): bake known-good L40S lc0 calibration + build guard (#150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Version bump, full gate, PR, release sequence

**Files:**
- Modify: `services/local_worker/pyproject.toml` (line 7: `version`)

- [ ] **Step 1: Bump the worker version**

In `services/local_worker/pyproject.toml`, change line 7 from `version = "0.9.14"` to:

```toml
version = "0.9.15"
```

- [ ] **Step 2: Run the full worker test suite + lint**

```bash
cd /Users/christopherwebster/Projects/wood_league/services/local_worker
python -m pytest -p no:cacheprovider -q
cd /Users/christopherwebster/Projects/wood_league
ruff check services/local_worker
```
Expected: all tests pass; ruff clean. Fix any failure before continuing (do not proceed with a red suite).

- [ ] **Step 3: Commit + open PR**

```bash
cd /Users/christopherwebster/Projects/wood_league
git add services/local_worker/pyproject.toml
git commit -m "chore(worker): bump 0.9.14 -> 0.9.15 (lc0 cold-start cache #150)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push -u origin issue/150-lc0-cold-start-cache
gh pr create --title "feat: lc0 cold-start cache — bake + bucket-persist (#150)" \
  --body "Closes #150. Implements docs/superpowers/specs/2026-05-17-lc0-cold-start-cache-design.md. Phase 1 bakes a captured L40S calibration into the image (build-guarded); Phase 2 persists per-fingerprint calibration to the bucket (fail-soft, mirrors cache_sync) with boot-pull via the lc0-tuning-pull CLI and auto-push via the get_tuned_opts on_calibrated hook. Phase 3 (TRT engine plan) deferred. Known limitation: fingerprint ignores GPU/lc0-version (lc0.py passes them empty) — self-heals on weights/backend change only.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 4: Release sequence (after PR merge — operator step, not automated)**

Per project `CLAUDE.md` (PyPI + image are tag-driven):

```bash
git checkout main && git pull --ff-only
git tag worker-v0.9.15 && git push origin worker-v0.9.15        # publishes PyPI
# Wait for the PyPI publish workflow to succeed, then build the image:
git tag vast-worker-v0.9.15 && git push origin vast-worker-v0.9.15
```

The `vast-worker-v0.9.15` build resolves `WORKER_VERSION=0.9.15` from the tag (#138) and bakes `wood-league-worker==0.9.15` + the L40S calibration. Re-point the vast template to the new image tag (operator, web UI) before the next paid campaign.

---

## Self-Review

**Spec coverage:**
- Pivotal constraint / per-fingerprint key → Task 1 (`tuning_object_key`, sha1 of canonical fingerprint).
- Phase 1 bake + build guard + piggyback capture + `data_dir()` pin → Task 6 (COPY to `/data/wlw/lc0_tuning.json`, the pinned runtime path; build guard mirrors existing Dockerfile guards).
- Phase 2 `pull_tuning`/`push_tuning` fail-soft → Task 1; boot pull → Task 4 + Task 5; auto-push → Task 2 + Task 3.
- Single `lc0_tuning.py` edit (one callback param) → Task 2 only.
- Self-healing on fingerprint change → emergent from `tuning_object_key` (Task 1) + pull/push; known GPU/version limitation documented in header, Task 7 PR body, and to be appended to the spec note.
- Testing requirements (key stability/sensitivity, pull/push fail-soft, callback once-on-miss/not-on-hit, default path unchanged) → Tasks 1–4 tests.
- Out-of-scope Phase 3 → not planned (correct).
- Version bump + release flow → Task 7.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to". Every code step has complete code. The only sequencing dependency (Task 6.1 capture gated on a trial) is explicit with exact commands.

**Type/name consistency:** `tuning_object_key`, `pull_tuning(client,bucket,fingerprint,dest)`, `push_tuning(client,bucket,cache_path)`, `push_after_calibrate(cache_path)`, `_fingerprint_from_env`, `lc0_tuning_pull`, `on_calibrated` — used identically across Tasks 1–4 and their tests. `compute_fingerprint`/`cache_path` imported from `local_worker.analysis.lc0_tuning` consistently. Fingerprint dict shape `{gpu,lc0_version,weights,backend}` consistent everywhere.

**Spec gap → action:** spec's "Phase 1 open item (pin `data_dir()`)" is resolved here (`/data/wlw`); spec's Risks table assumed a possible `data_dir()` mismatch — now eliminated. Append a one-line resolution note to the spec during execution (Task 7) so spec and plan agree.
