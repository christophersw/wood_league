"""Host-CPU probing: cgroup/affinity clamp so a sliced container does
not size Stockfish off the physical host (#134)."""
from pathlib import Path

from local_worker.analysis import host_cpu


def test_cgroup_v2_quota_parsed(tmp_path: Path, monkeypatch):
    f = tmp_path / "cpu.max"
    f.write_text("400000 100000\n")  # 4 CPUs
    monkeypatch.setattr(host_cpu, "_CGROUP_V2_MAX", f)
    assert host_cpu._cgroup_cpus() == 4.0


def test_cgroup_v2_unlimited_is_none(tmp_path: Path, monkeypatch):
    f = tmp_path / "cpu.max"
    f.write_text("max 100000\n")
    monkeypatch.setattr(host_cpu, "_CGROUP_V2_MAX", f)
    # v1 paths don't exist under tmp → overall None.
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_QUOTA", tmp_path / "nope-q")
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_PERIOD", tmp_path / "nope-p")
    assert host_cpu._cgroup_cpus() is None


def test_cgroup_v1_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(host_cpu, "_CGROUP_V2_MAX", tmp_path / "absent")
    q = tmp_path / "q"
    p = tmp_path / "p"
    q.write_text("150000\n")
    p.write_text("100000\n")
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_QUOTA", q)
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_PERIOD", p)
    assert host_cpu._cgroup_cpus() == 1.5


def test_cgroup_v1_unlimited_quota_is_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(host_cpu, "_CGROUP_V2_MAX", tmp_path / "absent")
    q = tmp_path / "q"
    p = tmp_path / "p"
    q.write_text("-1\n")  # unlimited
    p.write_text("100000\n")
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_QUOTA", q)
    monkeypatch.setattr(host_cpu, "_CGROUP_V1_PERIOD", p)
    assert host_cpu._cgroup_cpus() is None


def test_host_vcpu_clamps_to_cgroup(monkeypatch):
    # 64-core host, cgroup says 4 → host_vcpu must be 4 (#134).
    monkeypatch.setattr(host_cpu.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(host_cpu, "_affinity_cpus", lambda: 64)
    monkeypatch.setattr(host_cpu, "_cgroup_cpus", lambda: 4.0)
    assert host_cpu.host_vcpu() == 4


def test_host_vcpu_affinity_only(monkeypatch):
    monkeypatch.setattr(host_cpu.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(host_cpu, "_affinity_cpus", lambda: 8)
    monkeypatch.setattr(host_cpu, "_cgroup_cpus", lambda: None)
    assert host_cpu.host_vcpu() == 8
