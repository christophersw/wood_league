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
