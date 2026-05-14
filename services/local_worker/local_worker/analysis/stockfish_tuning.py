"""
Title: stockfish_tuning.py — Auto-tune Stockfish UCI options per host
Description:
    Derives Stockfish UCI options for the current host from cheap heuristics.
    Unlike lc0_tuning, there is no benchmark/calibration step — modern
    Stockfish has very predictable scaling on Threads/Hash and ships with
    NNUE enabled by default, so a one-shot heuristic suffices.

    Heuristics:
      - Threads = max(1, os.cpu_count() - 1) — leave one core for the OS
        and the worker process itself; fall back to 1 when cpu_count is None.
      - Hash    = min(2048, available_ram_mb // 4) — reserve up to 25% of
        currently-available RAM for the transposition table, capped at 2 GB
        so we never crowd out the rest of the worker stack. When psutil is
        unavailable, a conservative default of 1024 MB free RAM is assumed.

    UseNNUE is intentionally not set: every supported Stockfish build (v15+)
    enables NNUE by default and exposing the toggle would invite drift.

    The returned dict is consumed by analyze_pgn() and passed to
    engine.configure(); callers can opt out via auto_tune=False or override
    individual options by supplying their own threads/hash_mb arguments.

Changelog:
    2026-05-13: Initial creation (issue #67 subtask B).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# Cap the transposition table at 2 GB. Beyond this, returns diminish quickly
# at depth 20–25 (worker's typical depth band) and we risk evicting other
# allocations on smaller hosts.
_MAX_HASH_MB = 2048

# When psutil is missing we cannot probe free RAM. Assume a conservative
# 1 GB free, which yields a 256 MB hash budget — safe on every supported
# host, including 4 GB cloud workers.
_FALLBACK_FREE_RAM_MB = 1024


def _detect_free_ram_mb() -> int:
    """Return currently-available RAM in megabytes.

    Uses psutil.virtual_memory().available when psutil can be imported;
    otherwise falls back to a conservative constant so the heuristic still
    yields a usable Hash value on hosts without psutil.

    Returns:
        Integer megabytes of available RAM.
    """
    try:
        import psutil  # type: ignore[import-untyped]
    except ImportError:
        log.info(
            "stockfish_tuning: psutil unavailable; assuming %d MB free RAM",
            _FALLBACK_FREE_RAM_MB,
        )
        return _FALLBACK_FREE_RAM_MB
    return int(psutil.virtual_memory().available // (1024 * 1024))


def get_tuned_opts() -> dict[str, str]:
    """Compute heuristic Stockfish UCI options for the current host.

    Returns:
        Dict of UCI option name -> string value, ready to merge into the
        analyze_pgn() opts dict before engine.configure(). Always contains
        Threads and Hash; never contains UseNNUE (Stockfish defaults are fine).
    """
    cpu_count = os.cpu_count() or 1
    threads = max(1, cpu_count - 1)

    free_ram_mb = _detect_free_ram_mb()
    hash_mb = min(_MAX_HASH_MB, free_ram_mb // 4)
    # Guarantee a non-zero hash even on tiny hosts — Stockfish requires >= 1.
    hash_mb = max(1, hash_mb)

    return {
        "Threads": str(threads),
        "Hash": str(hash_mb),
    }
