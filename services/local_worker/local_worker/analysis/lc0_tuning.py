"""
Title: lc0_tuning.py — Auto-tune lc0 UCI options per host
Description:
    Derives lc0 UCI options for the current host in two layers:

    1. Cheap heuristics (run every session): Threads, NNCacheSize, RamLimitMb,
       SmartPruningFactor. Source = installed RAM, CPU count, backend family.

    2. One-shot calibration (run when no cache or fingerprint changed): shells
       out to `lc0 benchmark` at several MinibatchSize values, picks the highest
       nps, persists the result to a JSON cache in the user data dir.

    The cache is keyed by a fingerprint of (gpu, lc0_version, weights_path,
    backend). Changing any of those triggers recalibration on next call.

    The merged option dict is consumed by analyze_pgn() and passed to
    engine.configure(); callers can opt out via auto_tune=False.

Changelog:
    2026-05-13: Initial creation (issue #62).
    2026-05-13: Lower benchmark nodes to 50_000, raise timeout to 300s, and
        short-circuit the calibration sweep when the first batch size times
        out (issue #74).
    2026-05-14: Stop the MinibatchSize sweep as soon as nps regresses
        versus the previous successful measurement. Saves the 4–5 minute
        per-step cost (and the doomed mb=1024 timeout) on slower GPUs once
        the peak has been observed (issue #109).
    2026-05-15: Recognise the TensorRT (onnx-trt) backend — GPU thread
        heuristic + a dedicated L4-sized MinibatchSize sweep (issue #119).
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess  # noqa: S404 — required to run `lc0 benchmark`
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import psutil

from .._shared import data_dir

log = logging.getLogger(__name__)

# Each NN cache entry is roughly 200 bytes (lc0 reports ~64 bytes for the
# encoded position + value + policy head allocations). 200 is conservative.
_NN_CACHE_BYTES_PER_ENTRY = 200
_NN_CACHE_MIN_ENTRIES = 2_000_000
_NN_CACHE_MAX_ENTRIES = 30_000_000

_RAM_FRACTION_FOR_LIMIT = 0.5
_RAM_FRACTION_FOR_NN_CACHE = 0.05

# Backend-appropriate MinibatchSize sweeps. Metal regresses past 256; CPU
# backends are batch-insensitive so we don't sweep at all.
_BATCH_SWEEPS: dict[str, tuple[int, ...]] = {
    "cuda": (128, 256, 512, 1024),
    "metal": (64, 128, 256),
    # L4 (24 GB, Ada) under TensorRT sustains larger batches than the
    # 12 GB cuda-fp16 rig; the #109 early-regression stop trims doomed
    # large entries on smaller cards.
    "trt": (256, 512, 1024, 2048),
}

_BENCHMARK_NODES_PER_POSITION = 50_000
_BENCHMARK_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class HostInfo:
    """Read-only snapshot of the host's CPU, RAM and GPU situation."""

    backend: str
    cpu_count: int
    ram_total_bytes: int
    ram_available_bytes: int
    gpu_name: str = ""


def detect_host_info(backend: str, gpu_name: str = "") -> HostInfo:
    """Capture CPU/RAM facts for the current process.

    Args:
        backend: Lc0 backend name (e.g. 'cuda-fp16', 'metal', 'cpu'). Used to
            decide the Threads heuristic.
        gpu_name: Optional GPU label. Empty string when no GPU is present.

    Returns:
        Populated HostInfo dataclass.
    """
    vm = psutil.virtual_memory()
    return HostInfo(
        backend=backend,
        cpu_count=os.cpu_count() or 1,
        ram_total_bytes=vm.total,
        ram_available_bytes=vm.available,
        gpu_name=gpu_name,
    )


def _is_gpu_backend(backend: str) -> bool:
    """True if the backend offloads NN evaluation to a GPU."""
    lower = backend.lower()
    return (
        lower.startswith("cuda")
        or lower.startswith("metal")
        or "opencl" in lower
        or "trt" in lower
    )


def _batch_family(backend: str) -> Optional[str]:
    """Return the key used to look up a MinibatchSize sweep, or None."""
    lower = backend.lower()
    if "trt" in lower:
        return "trt"
    if lower.startswith("cuda"):
        return "cuda"
    if lower.startswith("metal"):
        return "metal"
    return None


def derive_heuristic_opts(host: HostInfo) -> dict[str, str]:
    """Compute UCI options from cheap host facts (no subprocess).

    Args:
        host: HostInfo for the current process.

    Returns:
        Dict of UCI option name → string value, ready for engine.configure().
    """
    if _is_gpu_backend(host.backend):
        threads = max(1, min(3, host.cpu_count // 2))
    else:
        threads = max(1, host.cpu_count - 1)

    nn_cache_target = int(
        host.ram_available_bytes * _RAM_FRACTION_FOR_NN_CACHE
        / _NN_CACHE_BYTES_PER_ENTRY
    )
    nn_cache = max(_NN_CACHE_MIN_ENTRIES, min(_NN_CACHE_MAX_ENTRIES, nn_cache_target))

    ram_limit_mb = int(host.ram_total_bytes * _RAM_FRACTION_FOR_LIMIT / (1024 * 1024))

    return {
        "Threads": str(threads),
        "NNCacheSize": str(nn_cache),
        "RamLimitMb": str(ram_limit_mb),
        # We always pass Limit(nodes=N) — no early stop wanted.
        "SmartPruningFactor": "0",
    }


def compute_fingerprint(
    gpu_name: str, lc0_version: str, weights_path: str, backend: str
) -> dict[str, str]:
    """Build the cache-invalidation key.

    Any change in this dict means the calibration cache is stale.

    Args:
        gpu_name: GPU label string (empty if no GPU).
        lc0_version: lc0 version string (e.g. 'v0.32.1').
        weights_path: Path to weights file (basename is used; path itself
            varies between hosts but the file's identity does not).
        backend: Lc0 backend (e.g. 'cuda-fp16').

    Returns:
        Plain-dict fingerprint suitable for JSON storage and equality compare.
    """
    return {
        "gpu": gpu_name,
        "lc0_version": lc0_version,
        "weights": Path(weights_path).name if weights_path else "",
        "backend": backend,
    }


def cache_path() -> Path:
    """Absolute path to the calibration cache JSON in user data dir."""
    return data_dir() / "lc0_tuning.json"


def load_cache(path: Optional[Path] = None) -> Optional[dict]:
    """Read the calibration cache JSON; return None if absent or malformed."""
    target = path or cache_path()
    try:
        return json.loads(target.read_text())
    except (OSError, ValueError):
        return None


def save_cache(payload: dict, path: Optional[Path] = None) -> None:
    """Persist the calibration cache JSON atomically (best-effort)."""
    target = path or cache_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    tmp.replace(target)


def parse_benchmark_nps(stdout: str) -> Optional[float]:
    """Extract the best 'NNN nps' reading from `lc0 benchmark` output.

    The format varies across lc0 versions: some print per-position lines, some
    a single total. We pick the largest nps reading observed.

    Args:
        stdout: Full stdout text from `lc0 benchmark`.

    Returns:
        Highest nps as float, or None if no nps line was found.
    """
    matches = re.findall(r"([\d,]+(?:\.\d+)?)\s*nps", stdout, flags=re.IGNORECASE)
    values: list[float] = []
    for raw in matches:
        try:
            values.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return max(values) if values else None


BenchmarkRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _default_benchmark_runner(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    """Run lc0 benchmark with a hard timeout; capture combined output.

    Args:
        cmd: Full argv list starting with the lc0 binary path.

    Returns:
        CompletedProcess with `.stdout` containing combined stdout+stderr.
    """
    return subprocess.run(  # noqa: S603 — argv is constructed from validated paths
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=_BENCHMARK_TIMEOUT_SECONDS,
    )


def _build_benchmark_cmd(
    lc0_path: str, weights_path: str, backend: str, minibatch_size: int
) -> list[str]:
    """Compose argv for one `lc0 benchmark` invocation at a given batch size."""
    cmd = [
        lc0_path,
        "benchmark",
        f"--nodes={_BENCHMARK_NODES_PER_POSITION}",
        f"--minibatch-size={minibatch_size}",
    ]
    if weights_path:
        cmd.append(f"--weights={weights_path}")
    if backend:
        cmd.append(f"--backend={backend}")
    return cmd


@dataclass(frozen=True)
class BenchmarkResult:
    """Outcome of one `lc0 benchmark` invocation.

    Attributes:
        nps: Parsed nodes-per-second reading, or None when the run failed
            or produced no nps reading.
        timed_out: True when the benchmark exceeded `_BENCHMARK_TIMEOUT_SECONDS`.
            Used by `calibrate()` to short-circuit the sweep when the very
            first batch size already times out (issue #74).
    """

    nps: Optional[float]
    timed_out: bool


def _measure_one_batch_size(
    lc0_path: str,
    weights_path: str,
    backend: str,
    minibatch_size: int,
    run: BenchmarkRunner,
) -> BenchmarkResult:
    """Run lc0 benchmark at a single MinibatchSize.

    Args:
        lc0_path: Absolute path to lc0 binary.
        weights_path: Path to weights file (may be empty).
        backend: Lc0 backend string.
        minibatch_size: MinibatchSize to pass via --minibatch-size=N.
        run: Benchmark runner callable (subprocess.run by default).

    Returns:
        BenchmarkResult with parsed nps (or None) and a `timed_out` flag so
        the caller can distinguish a hard timeout from other failure modes.
    """
    cmd = _build_benchmark_cmd(lc0_path, weights_path, backend, minibatch_size)
    try:
        completed = run(cmd)
    except subprocess.TimeoutExpired as exc:
        log.warning("lc0_tuning: benchmark mb=%d timed out: %s", minibatch_size, exc)
        return BenchmarkResult(nps=None, timed_out=True)
    except OSError as exc:
        log.warning("lc0_tuning: benchmark mb=%d failed: %s", minibatch_size, exc)
        return BenchmarkResult(nps=None, timed_out=False)
    combined = (completed.stdout or "") + (completed.stderr or "")
    nps = parse_benchmark_nps(combined)
    if nps is None:
        log.warning("lc0_tuning: benchmark mb=%d produced no nps reading",
                    minibatch_size)
        return BenchmarkResult(nps=None, timed_out=False)
    log.info("lc0_tuning: mb=%d -> %.0f nps", minibatch_size, nps)
    return BenchmarkResult(nps=nps, timed_out=False)


def _log_nps_regression(
    minibatch_size: int, previous_nps: float, current_nps: float
) -> None:
    """Log that the sweep is ending because nps has dropped."""
    log.info(
        "lc0_tuning: nps regressed at mb=%d (%.0f -> %.0f); ending sweep early",
        minibatch_size,
        previous_nps,
        current_nps,
    )


def _sweep_for_best(
    family: str,
    lc0_path: str,
    weights_path: str,
    backend: str,
    run: BenchmarkRunner,
) -> Optional[tuple[int, float]]:
    """Walk ``_BATCH_SWEEPS[family]`` and return the best ``(mb, nps)``.

    Aborts immediately if the first sweep entry hits the hard timeout
    (issue #74). Stops as soon as a successful measurement reports lower
    nps than the previous one — every subsequent step would burn 4–5
    minutes for a worse result, and on slow GPUs the largest entry tends
    to time out and kill the whole run (issue #109).

    Args:
        family: Sweep family key (e.g. ``"cuda"``, ``"metal"``).
        lc0_path: Absolute path to lc0 binary.
        weights_path: Path to weights file (may be empty).
        backend: Lc0 backend string.
        run: Benchmark runner callable.

    Returns:
        ``(minibatch_size, nps)`` of the best observed run, or ``None``
        if every invocation failed or the first entry timed out.
    """
    best: Optional[tuple[int, float]] = None
    last_nps: Optional[float] = None
    for index, minibatch_size in enumerate(_BATCH_SWEEPS[family]):
        outcome = _measure_one_batch_size(
            lc0_path, weights_path, backend, minibatch_size, run
        )
        if outcome.timed_out and index == 0:
            log.warning(
                "lc0_tuning: first sweep entry mb=%d timed out; "
                "aborting calibration",
                minibatch_size,
            )
            return None
        if outcome.nps is None:
            continue
        if best is None or outcome.nps > best[1]:
            best = (minibatch_size, outcome.nps)
        if last_nps is not None and outcome.nps < last_nps:
            _log_nps_regression(minibatch_size, last_nps, outcome.nps)
            break
        last_nps = outcome.nps
    return best


def calibrate(
    lc0_path: str,
    weights_path: str,
    backend: str,
    *,
    runner: Optional[BenchmarkRunner] = None,
) -> Optional[dict]:
    """Sweep MinibatchSize via `lc0 benchmark` and pick the highest-nps result.

    Returns None when the backend has no sweep table (e.g. pure CPU) or every
    invocation failed. Successful return shape::

        {"minibatch_size": int, "max_prefetch": int, "measured_nps": float}

    Args:
        lc0_path: Absolute path to lc0 binary.
        weights_path: Path to weights file (may be empty for engine default).
        backend: Lc0 backend (controls the sweep set).
        runner: Optional injection point for tests; defaults to subprocess.run.

    Returns:
        Best-found tuning dict, or None on total failure.
    """
    family = _batch_family(backend)
    if family is None:
        return None
    run = runner or _default_benchmark_runner

    best = _sweep_for_best(family, lc0_path, weights_path, backend, run)

    if best is None:
        return None
    minibatch, nps_val = best
    # MaxPrefetch ≈ minibatch_size / 4 is a sensible default for CUDA; lc0's
    # own default scales similarly. Clamp to a known-safe band.
    max_prefetch = max(32, min(256, minibatch // 4))
    return {
        "minibatch_size": minibatch,
        "max_prefetch": max_prefetch,
        "measured_nps": nps_val,
    }


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
    """Merge heuristic + calibration options for the current host.

    Calibration is skipped silently when the lc0 binary is missing, the
    backend has no sweep table, or every benchmark invocation fails. Heuristic
    options are always returned.

    Args:
        lc0_path: Path to lc0 binary (used only for calibration).
        weights_path: Network weights path (used for calibration + fingerprint).
        backend: Lc0 backend string.
        gpu_name: GPU label (or empty).
        lc0_version: lc0 version string for the fingerprint.
        cache_file: Optional cache path override (tests).
        runner: Optional benchmark runner override (tests).
        force_recalibrate: If True, ignore any cached calibration.
        on_calibrated: Optional callback invoked with the cache file
            path immediately after a *fresh* calibration is persisted
            (cache miss only). Used to push the result to durable
            storage; never called on a cache hit. Default None (no-op).

    Returns:
        Dict of UCI option name → string value ready for engine.configure().
    """
    host = detect_host_info(backend, gpu_name=gpu_name)
    opts = derive_heuristic_opts(host)

    fingerprint = compute_fingerprint(gpu_name, lc0_version, weights_path, backend)
    cache = None if force_recalibrate else load_cache(cache_file)
    if cache and cache.get("fingerprint") == fingerprint:
        opts["MinibatchSize"] = str(cache["minibatch_size"])
        opts["MaxPrefetch"] = str(cache["max_prefetch"])
        return opts

    if not shutil.which(lc0_path) and not Path(lc0_path).exists():
        log.info("lc0_tuning: lc0 binary not found; skipping calibration")
        return opts

    log.info("lc0_tuning: calibrating MinibatchSize for backend=%s …", backend)
    calibration = calibrate(lc0_path, weights_path, backend, runner=runner)
    if calibration is None:
        return opts

    opts["MinibatchSize"] = str(calibration["minibatch_size"])
    opts["MaxPrefetch"] = str(calibration["max_prefetch"])

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
