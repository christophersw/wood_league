"""
Title: test_cache_sync.py — Tests for the vast.ai eval-cache sync helpers
Description:
    Tests for ``cache_sync.snapshot_db`` (WAL-safe SQLite snapshot). More test
    cases added as ``cache_sync`` grows (pull/upload operations).

Changelog:
    2026-05-15: Initial creation (vast.ai bulk worker plan, sub-proj A+B).
"""
import sqlite3
from pathlib import Path

import local_worker.cache_sync as cs
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


class _UploadClient:
    def __init__(self):
        self.uploaded = None

    def upload_file(self, src, bucket, key):
        # Simulate S3 upload by copying the file before it's deleted
        import shutil
        preserved = Path(src).parent / f".uploaded_{Path(src).name}"
        shutil.copy(src, preserved)
        self.uploaded = (str(preserved), bucket, key)


def test_upload_delta_snapshots_then_uploads(tmp_path):
    live = tmp_path / "eval_cache.sqlite"
    conn = sqlite3.connect(live)
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
    snap = sqlite3.connect(src)
    assert snap.execute("SELECT k FROM t").fetchall() == [(1,)]
    snap.close()
    conn.close()
