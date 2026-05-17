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
