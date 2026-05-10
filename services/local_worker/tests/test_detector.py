"""
Title: test_detector.py — Tests for engine detection
Description:
    Tests that binary search and hardware detection produce valid output.

Changelog:
    2026-05-09: Initial creation
"""
from local_worker.detector import (
    find_binary,
    detect_lc0_backend,
    suggest_stockfish_settings,
    HardwareInfo,
    detect_hardware,
)


def test_find_binary_returns_none_for_nonexistent():
    result = find_binary("definitely_not_a_real_binary_xyz123")
    assert result is None


def test_find_binary_finds_python():
    # Python itself must be findable on PATH
    result = find_binary("python") or find_binary("python3")
    assert result is not None


def test_detect_hardware_returns_hardware_info():
    info = detect_hardware()
    assert isinstance(info, HardwareInfo)
    assert info.cpu_count >= 1
    assert info.ram_mb > 0


def test_suggest_stockfish_settings_sane_bounds():
    info = HardwareInfo(cpu_count=8, ram_mb=16384, has_cuda=False, has_apple_silicon=False)
    settings = suggest_stockfish_settings(info)
    assert 1 <= settings["threads"] <= 16
    assert 128 <= settings["hash_mb"] <= 8192


def test_detect_lc0_backend_returns_string():
    backend = detect_lc0_backend()
    assert backend in ("cuda-auto", "metal", "cpu")
