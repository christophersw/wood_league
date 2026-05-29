"""Tests for the pure Stockfish fan-out sizing helper."""
from local_worker.analysis.sf_fanout import FanoutPlan, effective_vcpu, plan_fanout


def test_effective_vcpu_cgroup_binds_below_cpu_count():
    # Sliced vast container: os.cpu_count() sees the 64-core host but the
    # cgroup quota is 4 CPUs — the quota must win (#134).
    assert effective_vcpu(cpu_count=64, affinity=64, cgroup_cpus=4.0) == 4


def test_effective_vcpu_affinity_binds():
    assert effective_vcpu(cpu_count=64, affinity=8, cgroup_cpus=None) == 8


def test_effective_vcpu_cpu_count_only():
    assert effective_vcpu(cpu_count=32, affinity=None, cgroup_cpus=None) == 32


def test_effective_vcpu_all_unknown_falls_back_to_one():
    assert effective_vcpu(cpu_count=None, affinity=None, cgroup_cpus=None) == 1


def test_effective_vcpu_fractional_cgroup_floors_min_one():
    assert effective_vcpu(cpu_count=64, affinity=64, cgroup_cpus=1.5) == 1


def test_effective_vcpu_ignores_nonpositive_signals():
    # cpu_count=0 / affinity=0 are bogus and must be ignored, not picked.
    assert effective_vcpu(cpu_count=0, affinity=0, cgroup_cpus=12.0) == 12


def test_effective_vcpu_feeds_plan_fanout_smaller_workers():
    # 64-core host but 16-CPU slice → fan-out sizes off 16, not 64.
    vcpu = effective_vcpu(cpu_count=64, affinity=16, cgroup_cpus=16.0)
    p = plan_fanout(vcpu=vcpu, avail_ram_mb=120_000, max_jobs=None)
    assert vcpu == 16
    assert p.workers == 3  # (16-4)//4


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


def test_gpus_default_one_matches_single_reserve():
    # gpus defaults to 1: reserve = 3*1 + 1 = 4 CPUs (unchanged baseline).
    # 32 vCPU, 120 GB → usable 28 // 4 = 7 Stockfish workers.
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=None)
    assert p.workers == 7


def test_gpus_scale_cpu_reserve():
    # 2 GPUs hold back 3*2 + 1 = 7 CPUs for two lc0 processes + OS.
    # 32 vCPU → usable 25 // 4 = 6 Stockfish workers (vs 7 at 1 GPU).
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=None, gpus=2)
    assert p.workers == 6


def test_gpus_scale_ram_reserve_binds_below_cpu():
    # RAM reserve = 6144*gpus + 1024 = 13312 MB at 2 GPUs.
    # 16 GB avail → budget 16384-13312 = 3072 // 768 = 4 ram_workers.
    # CPU allows 6 (32 vCPU, reserve 7), so RAM binds → 4.
    p = plan_fanout(vcpu=32, avail_ram_mb=16_384, max_jobs=None, gpus=2)
    assert p.workers == 4


def test_gpus_non_positive_treated_as_one():
    # A bogus gpus=0 must not zero-out the reserve; treat as a single GPU.
    p = plan_fanout(vcpu=32, avail_ram_mb=120_000, max_jobs=None, gpus=0)
    assert p.workers == 7
