"""
Title: test_lc0_tuning_pull_cmd.py — Tests for the lc0-tuning-pull command
Changelog:
    2026-05-17: Initial creation (issue #150).
"""
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


def test_lc0_tuning_pull_invokes_pull_to_cache_path(monkeypatch, tmp_path, capsys):
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
    assert "cache hit" in capsys.readouterr().out
