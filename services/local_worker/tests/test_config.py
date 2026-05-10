"""
Title: test_config.py — Tests for persistent configuration
Description: Verifies load/save/defaults for the Settings object.
Changelog:
    2026-05-09: Initial creation
"""
import json
import os
from pathlib import Path

import pytest

from local_worker.config import Settings, load_settings, save_settings


def test_defaults_when_no_file(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = load_settings(cfg_file)
    assert s.api_url == ""
    assert s.api_key == ""
    assert s.stockfish_path == ""
    assert s.lc0_path == ""
    assert s.default_batch_size == 5
    assert s.stockfish_depth == 20
    assert s.stockfish_threads == 4
    assert s.stockfish_hash_mb == 512
    assert s.lc0_nodes == 10000
    assert s.default_engines == ["stockfish"]
    assert s.syzygy_path == ""


def test_round_trip(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = Settings(api_url="https://example.com", api_key="mykey", stockfish_depth=25)
    save_settings(s, cfg_file)
    loaded = load_settings(cfg_file)
    assert loaded.api_url == "https://example.com"
    assert loaded.api_key == "mykey"
    assert loaded.stockfish_depth == 25


def test_is_configured_false_without_key(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = load_settings(cfg_file)
    assert not s.is_configured()


def test_is_configured_true_with_url_and_key(tmp_path):
    cfg_file = tmp_path / "settings.json"
    s = Settings(api_url="https://example.com", api_key="mykey")
    save_settings(s, cfg_file)
    loaded = load_settings(cfg_file)
    assert loaded.is_configured()
