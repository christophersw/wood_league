"""
Title: test_lc0_tuning.py — Unit tests for the lc0 auto-tuner
Description:
    Covers heuristic derivation across backend/RAM/CPU permutations, fingerprint
    invalidation, JSON cache round-trip, lc0-benchmark stdout parsing, and the
    calibrate()/get_tuned_opts() orchestration via an injected fake runner.
    No lc0 binary is required.

Changelog:
    2026-05-13: Initial creation (issue #62).
    2026-05-13: Add regression for first-batch timeout short-circuit (issue #74).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from local_worker.analysis import lc0_tuning
from local_worker.analysis.lc0_tuning import (
    HostInfo,
    calibrate,
    compute_fingerprint,
    derive_heuristic_opts,
    get_tuned_opts,
    load_cache,
    parse_benchmark_nps,
    save_cache,
)


def _gb(n: float) -> int:
    """Helper: GB → bytes."""
    return int(n * 1024 ** 3)


# ---------------------------------------------------------------------------
# Heuristic derivation
# ---------------------------------------------------------------------------

def test_heuristics_gpu_caps_threads_at_three():
    host = HostInfo(
        backend="cuda-fp16",
        cpu_count=24,
        ram_total_bytes=_gb(64),
        ram_available_bytes=_gb(40),
    )
    opts = derive_heuristic_opts(host)
    assert opts["Threads"] == "3"
    assert opts["SmartPruningFactor"] == "0"
    assert int(opts["NNCacheSize"]) <= 30_000_000
    assert int(opts["NNCacheSize"]) >= 2_000_000
    assert int(opts["RamLimitMb"]) == _gb(64) * 0.5 // (1024 * 1024)


def test_heuristics_cpu_backend_uses_more_threads():
    host = HostInfo(
        backend="eigen",
        cpu_count=8,
        ram_total_bytes=_gb(16),
        ram_available_bytes=_gb(8),
    )
    opts = derive_heuristic_opts(host)
    assert opts["Threads"] == "7"


def test_heuristics_trt_backend_is_gpu():
    host = HostInfo(
        backend="onnx-trt",
        cpu_count=24,
        ram_total_bytes=_gb(64),
        ram_available_bytes=_gb(40),
    )
    opts = derive_heuristic_opts(host)
    # GPU backends cap Threads at 3; a CPU backend on 24 cores would give 23.
    assert opts["Threads"] == "3"


def test_nn_cache_floor_on_low_ram():
    host = HostInfo(
        backend="metal",
        cpu_count=8,
        ram_total_bytes=_gb(8),
        ram_available_bytes=_gb(1),
    )
    opts = derive_heuristic_opts(host)
    assert int(opts["NNCacheSize"]) == 2_000_000


def test_nn_cache_ceiling_on_huge_ram():
    host = HostInfo(
        backend="cuda-fp16",
        cpu_count=32,
        ram_total_bytes=_gb(256),
        ram_available_bytes=_gb(200),
    )
    opts = derive_heuristic_opts(host)
    assert int(opts["NNCacheSize"]) == 30_000_000


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------

def test_fingerprint_changes_when_gpu_changes():
    a = compute_fingerprint("RTX 4070 Ti", "v0.32.1", "/x/BT4.pb.gz", "cuda-fp16")
    b = compute_fingerprint("RTX 4080", "v0.32.1", "/x/BT4.pb.gz", "cuda-fp16")
    assert a != b


def test_fingerprint_ignores_weights_path_dir():
    a = compute_fingerprint("RTX 4070", "v0.32.1", "/a/BT4.pb.gz", "cuda-fp16")
    b = compute_fingerprint("RTX 4070", "v0.32.1", "/b/BT4.pb.gz", "cuda-fp16")
    assert a == b


# ---------------------------------------------------------------------------
# Cache I/O
# ---------------------------------------------------------------------------

def test_cache_roundtrip(tmp_path: Path):
    cache = tmp_path / "tune.json"
    payload = {"fingerprint": {"gpu": "x"}, "minibatch_size": 512}
    save_cache(payload, cache)
    assert load_cache(cache) == payload


def test_load_cache_missing_returns_none(tmp_path: Path):
    assert load_cache(tmp_path / "nope.json") is None


def test_load_cache_corrupt_returns_none(tmp_path: Path):
    cache = tmp_path / "corrupt.json"
    cache.write_text("{not valid json")
    assert load_cache(cache) is None


# ---------------------------------------------------------------------------
# Benchmark output parsing
# ---------------------------------------------------------------------------

def test_parse_benchmark_picks_highest_nps():
    text = "Position 1: 12345 nps\nPosition 2: 23456 nps\nTotal: 18000 nps\n"
    assert parse_benchmark_nps(text) == 23456.0


def test_parse_benchmark_handles_commas():
    text = "Total: 1,234,567 nps\n"
    assert parse_benchmark_nps(text) == 1_234_567.0


def test_parse_benchmark_returns_none_when_absent():
    assert parse_benchmark_nps("no relevant lines here") is None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def _fake_completed(stdout: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_calibrate_picks_fastest_minibatch_size():
    nps_by_batch = {128: 10_000, 256: 22_000, 512: 28_000, 1024: 21_000}
    seen_batches: list[int] = []

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        seen_batches.append(mb)
        return _fake_completed(f"Total: {nps_by_batch[mb]} nps\n")

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "cuda-fp16", runner=runner)

    assert result is not None
    assert result["minibatch_size"] == 512
    assert result["measured_nps"] == 28_000
    assert sorted(seen_batches) == [128, 256, 512, 1024]


def test_calibrate_metal_uses_smaller_sweep():
    seen_batches: list[int] = []

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        seen_batches.append(mb)
        return _fake_completed("Total: 5000 nps\n")

    calibrate("/fake/lc0", "/fake/net.pb.gz", "metal", runner=runner)

    assert sorted(seen_batches) == [64, 128, 256]


def test_calibrate_cpu_backend_returns_none():
    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":  # pragma: no cover
        raise AssertionError("runner must not be invoked for CPU backend")

    assert calibrate("/fake/lc0", "/fake/net.pb.gz", "eigen", runner=runner) is None


def test_calibrate_aborts_when_first_batch_times_out():
    """Issue #74: a timeout on the first batch size aborts the sweep entirely.

    Large nets (e.g. BT4-1024x15x32h) on modest GPUs may exceed the hard
    benchmark timeout even at the smallest MinibatchSize in the sweep. When
    that happens, larger batch sizes will only be slower, so we short-circuit
    the rest of the sweep instead of burning the full timeout for each one.
    """
    call_count = {"n": 0}

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        call_count["n"] += 1
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "cuda-fp16", runner=runner)

    assert result is None
    assert call_count["n"] == 1


def test_calibrate_continues_when_non_first_batch_times_out():
    """A timeout on a later batch is tolerated; earlier successes still win."""
    call_count = {"n": 0}

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        call_count["n"] += 1
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        if mb == 128:
            return _fake_completed("Total: 12000 nps\n")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "cuda-fp16", runner=runner)

    assert result is not None
    assert result["minibatch_size"] == 128
    assert call_count["n"] == 4


def test_calibrate_stops_when_nps_regresses():
    """Issue #109: stop the sweep once a measurement drops below the prior.

    On slow GPUs, peak nps is reached early (mb=128) and every additional
    sweep step burns 4–5 minutes for a worse result — and the largest entry
    tends to time out and kill the run. Verify the sweep ends after the first
    regression and the best earlier result wins.
    """
    call_count = {"n": 0}
    nps_by_mb = {128: 17772.0, 256: 13721.0, 512: 13569.0, 1024: 8000.0}

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        call_count["n"] += 1
        mb = next(
            int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size=")
        )
        return _fake_completed(f"Total: {nps_by_mb[mb]:.0f} nps\n")

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "cuda-fp16", runner=runner)

    assert result is not None
    assert result["minibatch_size"] == 128
    assert result["measured_nps"] == 17772.0
    # Should have run mb=128 then mb=256 (first regression), then stopped.
    assert call_count["n"] == 2


def test_calibrate_skips_batches_with_unparseable_output():
    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        return _fake_completed("ok\n" if mb == 128 else "Total: 9000 nps\n")

    result = calibrate("/fake/lc0", "/fake/net.pb.gz", "cuda-fp16", runner=runner)
    assert result is not None
    assert result["minibatch_size"] in {256, 512, 1024}


# ---------------------------------------------------------------------------
# Orchestration: get_tuned_opts
# ---------------------------------------------------------------------------

def test_get_tuned_opts_uses_cache_when_fingerprint_matches(
    tmp_path: Path, monkeypatch
):
    cache = tmp_path / "tune.json"
    fingerprint = compute_fingerprint("RTX 4070 Ti", "v0.32.1", "BT4.pb.gz", "cuda-fp16")
    save_cache(
        {
            "fingerprint": fingerprint,
            "minibatch_size": 768,
            "max_prefetch": 192,
            "measured_nps": 30000,
            "calibrated_at": "2026-01-01T00:00:00Z",
        },
        cache,
    )

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":  # pragma: no cover
        raise AssertionError("runner must not be called when cache is fresh")

    opts = get_tuned_opts(
        lc0_path="/fake/lc0",
        weights_path="BT4.pb.gz",
        backend="cuda-fp16",
        gpu_name="RTX 4070 Ti",
        lc0_version="v0.32.1",
        cache_file=cache,
        runner=runner,
    )
    assert opts["MinibatchSize"] == "768"
    assert opts["MaxPrefetch"] == "192"
    assert "Threads" in opts


def test_get_tuned_opts_recalibrates_on_fingerprint_mismatch(tmp_path: Path):
    cache = tmp_path / "tune.json"
    save_cache(
        {
            "fingerprint": {"gpu": "old", "lc0_version": "v0.31",
                            "weights": "old.pb.gz", "backend": "cuda-fp16"},
            "minibatch_size": 128,
            "max_prefetch": 32,
            "measured_nps": 5000,
            "calibrated_at": "2026-01-01T00:00:00Z",
        },
        cache,
    )

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        return _fake_completed(f"Total: {1000 * mb} nps\n")

    opts = get_tuned_opts(
        lc0_path=__file__,  # any existing path
        weights_path="BT4.pb.gz",
        backend="cuda-fp16",
        gpu_name="RTX 4070 Ti",
        lc0_version="v0.32.1",
        cache_file=cache,
        runner=runner,
    )
    assert opts["MinibatchSize"] == "1024"
    updated = json.loads(cache.read_text())
    assert updated["minibatch_size"] == 1024
    assert updated["fingerprint"]["gpu"] == "RTX 4070 Ti"


def test_get_tuned_opts_returns_heuristics_when_lc0_missing(tmp_path: Path):
    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":  # pragma: no cover
        raise AssertionError("runner must not be called when lc0 is absent")

    opts = get_tuned_opts(
        lc0_path=str(tmp_path / "does-not-exist"),
        weights_path="BT4.pb.gz",
        backend="cuda-fp16",
        gpu_name="RTX 4070 Ti",
        lc0_version="v0.32.1",
        cache_file=tmp_path / "tune.json",
        runner=runner,
    )
    assert "MinibatchSize" not in opts
    assert opts["Threads"] in {"1", "2", "3"}
    assert opts["SmartPruningFactor"] == "0"


def test_get_tuned_opts_cpu_backend_skips_calibration_silently(tmp_path: Path):
    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":  # pragma: no cover
        raise AssertionError("CPU backend should not invoke benchmark")

    opts = get_tuned_opts(
        lc0_path=__file__,
        weights_path="",
        backend="eigen",
        gpu_name="",
        lc0_version="v0.32.1",
        cache_file=tmp_path / "tune.json",
        runner=runner,
    )
    assert "MinibatchSize" not in opts
    assert opts["SmartPruningFactor"] == "0"


def test_get_tuned_opts_force_recalibrate_ignores_cache(tmp_path: Path):
    cache = tmp_path / "tune.json"
    fingerprint = compute_fingerprint("gpu-a", "v0.32.1", "n.pb.gz", "cuda-fp16")
    save_cache(
        {
            "fingerprint": fingerprint,
            "minibatch_size": 128,
            "max_prefetch": 32,
            "measured_nps": 1.0,
            "calibrated_at": "old",
        },
        cache,
    )

    def runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
        mb = next(int(c.split("=", 1)[1]) for c in cmd if c.startswith("--minibatch-size="))
        return _fake_completed(f"Total: {mb * 100} nps\n")

    opts = get_tuned_opts(
        lc0_path=__file__,
        weights_path="n.pb.gz",
        backend="cuda-fp16",
        gpu_name="gpu-a",
        lc0_version="v0.32.1",
        cache_file=cache,
        runner=runner,
        force_recalibrate=True,
    )
    assert opts["MinibatchSize"] == "1024"


# Sanity import to ensure the module's public surface is stable.
def test_module_exports_expected_helpers():
    assert callable(lc0_tuning.detect_host_info)
    assert callable(lc0_tuning.derive_heuristic_opts)
    assert callable(lc0_tuning.compute_fingerprint)
    assert callable(lc0_tuning.calibrate)
    assert callable(lc0_tuning.get_tuned_opts)
