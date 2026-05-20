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
    _FP3 = {**_FP, "gpu": "RTX 4090"}
    assert ts.tuning_object_key(_FP) != ts.tuning_object_key(_FP3)


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


def test_pull_tuning_removes_preexisting_file_on_error(tmp_path):
    client = _PullClient(raise_on_download=True)
    dest = tmp_path / "lc0_tuning.json"
    dest.write_text("STALE")
    ok = ts.pull_tuning(client, "wl-bucket", _FP, dest)
    assert ok is False
    assert not dest.exists()


def test_push_after_calibrate_noop_without_bucket(monkeypatch, tmp_path):
    monkeypatch.delenv("RAILWAY_BUCKET_NAME", raising=False)
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP}))
    called = []
    monkeypatch.setattr(ts, "push_tuning", lambda *a, **k: called.append(1))
    ts.push_after_calibrate(cache)  # must not raise
    assert called == []  # no bucket → never attempts a push


def test_push_after_calibrate_failsoft_on_client_init_error(monkeypatch, tmp_path):
    monkeypatch.setenv("RAILWAY_BUCKET_NAME", "wl-bucket")
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP}))

    def boom():
        raise RuntimeError("creds missing")

    monkeypatch.setattr(ts, "make_s3_client", boom)
    ts.push_after_calibrate(cache)  # must not raise


def test_push_tuning_failsoft_when_fingerprint_key_missing(tmp_path):
    """A cache file lacking the 'fingerprint' key must not raise; nothing uploaded."""
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"minibatch_size": 256}))  # no 'fingerprint'
    client = _PushClient()
    ts.push_tuning(client, "wl-bucket", cache)  # must not raise
    assert client.uploaded is None


# ---------------------------------------------------------------------------
# draw_rate section — push_draw_rate / pull_draw_rate
# ---------------------------------------------------------------------------

def test_push_pull_draw_rate_round_trips(tmp_path):
    """push_draw_rate then pull_draw_rate returns the same value for a network."""
    cache = tmp_path / "lc0_tuning.json"
    # pre-populate with minibatch data to confirm we don't clobber it
    cache.write_text(json.dumps({"fingerprint": _FP, "minibatch_size": 256}))
    ts.push_draw_rate("BT4", 0.42, cache)
    pulled = ts.pull_draw_rate("BT4", cache)
    assert pulled is not None
    assert abs(pulled - 0.42) < 1e-9
    # existing keys untouched
    payload = json.loads(cache.read_text())
    assert payload["minibatch_size"] == 256


def test_push_pull_draw_rate_multiple_networks(tmp_path):
    """Multiple networks can be stored and retrieved independently."""
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP}))
    ts.push_draw_rate("net-a", 0.35, cache)
    ts.push_draw_rate("net-b", 0.55, cache)
    assert abs(ts.pull_draw_rate("net-a", cache) - 0.35) < 1e-9
    assert abs(ts.pull_draw_rate("net-b", cache) - 0.55) < 1e-9


def test_pull_draw_rate_missing_network_returns_none(tmp_path):
    """pull_draw_rate returns None for a network not yet stored."""
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text(json.dumps({"fingerprint": _FP}))
    assert ts.pull_draw_rate("unknown-net", cache) is None


def test_pull_draw_rate_missing_file_returns_none(tmp_path):
    """pull_draw_rate returns None (fail-soft) when the cache file is absent."""
    cache = tmp_path / "does_not_exist.json"
    assert ts.pull_draw_rate("BT4", cache) is None


def test_pull_draw_rate_corrupt_file_returns_none(tmp_path):
    """pull_draw_rate returns None (fail-soft) when the cache file is corrupt JSON."""
    cache = tmp_path / "lc0_tuning.json"
    cache.write_text("{ NOT VALID JSON !!!")
    assert ts.pull_draw_rate("BT4", cache) is None


def test_push_draw_rate_creates_file_if_absent(tmp_path):
    """push_draw_rate creates lc0_tuning.json when it does not yet exist."""
    cache = tmp_path / "lc0_tuning.json"
    ts.push_draw_rate("net-new", 0.30, cache)
    assert cache.exists()
    pulled = ts.pull_draw_rate("net-new", cache)
    assert abs(pulled - 0.30) < 1e-9


def test_push_draw_rate_failsoft_on_io_error(tmp_path):
    """push_draw_rate does not raise when writing fails (e.g. read-only dir)."""
    # Point at a path inside a file (not a dir) so write will fail
    fake_dir = tmp_path / "not_a_dir.txt"
    fake_dir.write_text("I am a file")
    cache = fake_dir / "lc0_tuning.json"  # cannot write inside a file
    # Must not raise
    ts.push_draw_rate("BT4", 0.5, cache)
