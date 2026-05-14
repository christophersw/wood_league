"""
Title: test_config_env.py — Tests for WLW_* env-var settings overrides
Description:
    Verifies that ``load_settings`` honours ``WLW_*`` environment variables
    on top of (or in place of) the on-disk JSON settings file, and that
    ``_shared.data_dir()`` respects ``WLW_DATA_DIR``. Added for the RunPod
    deployment feature (issue #79).

Changelog:
    2026-05-14: Initial creation.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from local_worker import _shared
from local_worker.config import Settings, load_settings, save_settings


# Every ``WLW_*`` env var the worker recognises — cleared before each test
# so suite ordering and the developer's shell can't pollute the inputs.
_WLW_ENV_VARS = (
    "WLW_API_URL",
    "WLW_API_KEY",
    "WLW_WORKER_ID",
    "WLW_STOCKFISH_PATH",
    "WLW_LC0_PATH",
    "WLW_LC0_WEIGHTS_PATH",
    "WLW_LC0_BACKEND",
    "WLW_SYZYGY_PATH",
    "WLW_LC0_NODES",
    "WLW_STOCKFISH_DEPTH",
    "WLW_STOCKFISH_THREADS",
    "WLW_STOCKFISH_HASH_MB",
    "WLW_EVAL_CACHE_MAX_MB",
    "WLW_DEFAULT_BATCH_SIZE",
    "WLW_BATCH_TIME_MINUTES",
    "WLW_EVAL_CACHE_ENABLED",
    "WLW_DEFAULT_ENGINES",
    "WLW_DATA_DIR",
)


@pytest.fixture(autouse=True)
def _clear_wlw_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every WLW_* override before each test for a clean baseline."""
    for name in _WLW_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_env_overrides_existing_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env vars must override values loaded from the JSON file."""
    cfg_file = tmp_path / "settings.json"
    save_settings(
        Settings(api_url="https://disk.example", api_key="disk-key", stockfish_depth=18),
        cfg_file,
    )
    monkeypatch.setenv("WLW_API_URL", "https://env.example")
    monkeypatch.setenv("WLW_API_KEY", "env-key")
    monkeypatch.setenv("WLW_STOCKFISH_DEPTH", "27")

    loaded = load_settings(cfg_file)

    assert loaded.api_url == "https://env.example"
    assert loaded.api_key == "env-key"
    assert loaded.stockfish_depth == 27


def test_env_supplies_settings_without_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Env vars must populate settings when no JSON file exists on disk."""
    monkeypatch.setenv("WLW_API_URL", "host.example")  # schemeless on purpose
    monkeypatch.setenv("WLW_API_KEY", "from-env")
    monkeypatch.setenv("WLW_LC0_NODES", "20000")

    loaded = load_settings(tmp_path / "missing.json")

    assert loaded.api_url == "https://host.example"
    assert loaded.api_key == "from-env"
    assert loaded.lc0_nodes == 20000
    assert loaded.is_configured()


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1", True),
        ("0", False),
        ("true", True),
        ("FALSE", False),
        ("Yes", True),
        ("no", False),
    ],
)
def test_eval_cache_enabled_bool_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str, expected: bool
) -> None:
    """``WLW_EVAL_CACHE_ENABLED`` must parse common truthy/falsy spellings."""
    monkeypatch.setenv("WLW_EVAL_CACHE_ENABLED", raw)
    loaded = load_settings(tmp_path / "missing.json")
    assert loaded.eval_cache_enabled is expected


def test_default_engines_list_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``WLW_DEFAULT_ENGINES`` must split on commas, trimming whitespace."""
    monkeypatch.setenv("WLW_DEFAULT_ENGINES", "stockfish, lc0")
    loaded = load_settings(tmp_path / "missing.json")
    assert loaded.default_engines == ["stockfish", "lc0"]


def test_data_dir_honours_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``_shared.data_dir()`` must use ``WLW_DATA_DIR`` when set."""
    target = tmp_path / "runpod-volume"
    monkeypatch.setenv("WLW_DATA_DIR", str(target))

    resolved = _shared.data_dir()

    assert resolved == target
    assert resolved.is_dir()


def test_data_dir_falls_back_to_platformdirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without the env var, ``data_dir()`` must defer to platformdirs."""
    sentinel = tmp_path / "fallback"
    monkeypatch.delenv("WLW_DATA_DIR", raising=False)
    monkeypatch.setattr(
        _shared.platformdirs,
        "user_data_dir",
        lambda *_args, **_kwargs: str(sentinel),
    )

    resolved = _shared.data_dir()

    assert resolved == sentinel


def test_invalid_int_env_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A junk int value must not crash startup; defaults stay intact."""
    monkeypatch.setenv("WLW_STOCKFISH_DEPTH", "not-an-int")
    loaded = load_settings(tmp_path / "missing.json")
    assert loaded.stockfish_depth == 20


def test_json_loaded_when_no_env(tmp_path: Path) -> None:
    """Sanity: with no env overrides, JSON values still flow through."""
    cfg_file = tmp_path / "settings.json"
    payload = {"api_url": "https://disk.example", "api_key": "disk-key"}
    cfg_file.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_settings(cfg_file)
    assert loaded.api_url == "https://disk.example"
    assert loaded.api_key == "disk-key"
