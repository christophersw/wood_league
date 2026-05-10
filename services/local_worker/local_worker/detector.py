"""
Title: detector.py — Engine binary detection and hardware sensing
Description:
    Locates Stockfish and Lc0 binaries across Windows/Mac/Linux, detects
    available compute backends (CUDA, Metal, CPU), and suggests default
    engine settings based on available hardware.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass
class HardwareInfo:
    """Snapshot of locally available compute resources."""

    cpu_count: int
    ram_mb: int
    has_cuda: bool
    has_apple_silicon: bool


_STOCKFISH_CANDIDATES = [
    "stockfish",
    "/usr/games/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    r"C:\Program Files\Stockfish\stockfish.exe",
]

_LC0_CANDIDATES = [
    "lc0",
    "/usr/local/bin/lc0",
    "/opt/homebrew/bin/lc0",
    r"C:\Program Files\Lc0\lc0.exe",
]


def find_binary(name: str, extra_paths: Optional[list[str]] = None) -> Optional[str]:
    """Search PATH and known locations for a binary by name.

    Args:
        name: Binary name or absolute path to try.
        extra_paths: Additional candidate paths to check.

    Returns:
        Absolute path string if found, None otherwise.
    """
    found = shutil.which(name)
    if found:
        return found
    for candidate in (extra_paths or []):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def find_stockfish() -> Optional[str]:
    """Search for a Stockfish binary.

    Returns:
        Path to stockfish binary, or None if not found.
    """
    return find_binary("stockfish", _STOCKFISH_CANDIDATES)


def find_lc0() -> Optional[str]:
    """Search for an Lc0 binary.

    Returns:
        Path to lc0 binary, or None if not found.
    """
    return find_binary("lc0", _LC0_CANDIDATES)


def _has_cuda() -> bool:
    """Return True if an NVIDIA GPU with CUDA is available."""
    return shutil.which("nvidia-smi") is not None


def _has_apple_silicon() -> bool:
    """Return True if running on Apple Silicon (M1/M2/M3/M4)."""
    return sys.platform == "darwin" and platform.machine() == "arm64"


def detect_hardware() -> HardwareInfo:
    """Probe the system for CPU, RAM, and GPU capabilities.

    Returns:
        HardwareInfo with cpu_count, ram_mb, has_cuda, has_apple_silicon.
    """
    import os
    cpu_count = os.cpu_count() or 1

    ram_mb = 4096  # safe default
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            ram_mb = int(result.stdout.strip()) // (1024 * 1024)
        elif sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_mb = int(line.split()[1]) // 1024
                        break
        elif sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            mem_status = ctypes.c_ulong(0)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
    except Exception:
        pass

    return HardwareInfo(
        cpu_count=cpu_count,
        ram_mb=ram_mb,
        has_cuda=_has_cuda(),
        has_apple_silicon=_has_apple_silicon(),
    )


def detect_lc0_backend() -> str:
    """Determine the best Lc0 compute backend for this machine.

    Returns:
        Backend string: 'cuda-auto', 'metal', or 'cpu'.
    """
    if _has_cuda():
        return "cuda-auto"
    if _has_apple_silicon():
        return "metal"
    return "cpu"


def suggest_stockfish_settings(hw: HardwareInfo) -> dict[str, int]:
    """Suggest sensible Stockfish thread/hash settings for this hardware.

    Args:
        hw: HardwareInfo from detect_hardware().

    Returns:
        Dict with 'threads' and 'hash_mb' keys.
    """
    threads = max(1, hw.cpu_count - 1)
    threads = min(threads, 16)
    hash_mb = max(128, min(hw.ram_mb // 4, 8192))
    return {"threads": threads, "hash_mb": hash_mb}
