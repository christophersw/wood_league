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
