"""
Title: config.py — Persistent worker configuration
Description:
    Loads and saves worker settings to a JSON file in the platform-standard
    user data directory. Provides sensible defaults for all settings and
    supports overriding any field via ``WLW_*`` environment variables —
    primarily for containerised / RunPod deployments where mutating an
    on-disk settings file is awkward.

Changelog:
    2026-05-09: Initial creation
    2026-05-14: Add ``WLW_*`` env-var overrides for RunPod deployment (#79).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import platformdirs


def _default_config_path() -> Path:
    """Return the platform-appropriate path for the settings file."""
    data_dir = Path(platformdirs.user_data_dir("wood-league-worker", "WoodLeague"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "settings.json"


@dataclass
class Settings:
    """All persistent worker settings."""

    api_url: str = ""
    api_key: str = ""
    worker_id: str = ""
    stockfish_path: str = ""
    lc0_path: str = ""
    lc0_weights_path: str = ""
    syzygy_path: str = ""
    lc0_backend: str = ""
    default_engines: list[str] = field(default_factory=lambda: ["stockfish"])
    default_batch_size: int = 5
    batch_time_minutes: Optional[int] = None
    stockfish_depth: int = 20
    stockfish_threads: int = 4
    stockfish_hash_mb: int = 512
    lc0_nodes: int = 10000
    eval_cache_enabled: bool = True
    eval_cache_max_mb: int = 500

    def is_configured(self) -> bool:
        """Return True if the minimum required settings are present."""
        return bool(self.api_url and self.api_key)


def normalize_api_url(url: str) -> str:
    """Return the api_url with a scheme, defaulting to https:// when missing.

    Args:
        url: A possibly schemeless URL like "example.com" or "host:8000".

    Returns:
        The same URL with a leading "https://" if no scheme was present. An
        empty string is returned unchanged so is_configured() still reports
        False for unconfigured installs.
    """
    stripped = url.strip()
    if not stripped:
        return ""
    if "://" in stripped:
        return stripped
    return f"https://{stripped}"


# Mapping of ``WLW_*`` env var names to ``Settings`` string-typed fields.
_STRING_ENV_FIELDS: dict[str, str] = {
    "WLW_API_URL": "api_url",
    "WLW_API_KEY": "api_key",
    "WLW_WORKER_ID": "worker_id",
    "WLW_STOCKFISH_PATH": "stockfish_path",
    "WLW_LC0_PATH": "lc0_path",
    "WLW_LC0_WEIGHTS_PATH": "lc0_weights_path",
    "WLW_LC0_BACKEND": "lc0_backend",
    "WLW_SYZYGY_PATH": "syzygy_path",
}

# Mapping of ``WLW_*`` env var names to ``Settings`` int-typed fields.
_INT_ENV_FIELDS: dict[str, str] = {
    "WLW_LC0_NODES": "lc0_nodes",
    "WLW_STOCKFISH_DEPTH": "stockfish_depth",
    "WLW_STOCKFISH_THREADS": "stockfish_threads",
    "WLW_STOCKFISH_HASH_MB": "stockfish_hash_mb",
    "WLW_EVAL_CACHE_MAX_MB": "eval_cache_max_mb",
    "WLW_DEFAULT_BATCH_SIZE": "default_batch_size",
}


def _parse_bool(raw: str) -> bool:
    """Parse a human-friendly boolean string.

    Args:
        raw: A string like ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).

    Returns:
        True for ``1/true/yes`` (case-insensitive); False for ``0/false/no``.
        Falls back to ``bool(raw)`` for anything else so callers can still
        pass non-empty truthy values without crashing.
    """
    lowered = raw.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(lowered)


def _apply_string_overrides(settings: Settings) -> None:
    """Apply all string-typed ``WLW_*`` overrides to ``settings`` in place."""
    for env_name, field_name in _STRING_ENV_FIELDS.items():
        value = os.environ.get(env_name)
        if value:
            setattr(settings, field_name, value)


def _apply_int_overrides(settings: Settings) -> None:
    """Apply all int-typed ``WLW_*`` overrides to ``settings`` in place.

    Invalid integers are silently ignored so a typo in the RunPod console
    doesn't crash the worker — the prior value remains intact.
    """
    for env_name, field_name in _INT_ENV_FIELDS.items():
        value = os.environ.get(env_name)
        if not value:
            continue
        try:
            setattr(settings, field_name, int(value))
        except ValueError:
            continue


def _apply_optional_int_override(settings: Settings) -> None:
    """Apply the optional-int ``WLW_BATCH_TIME_MINUTES`` override."""
    raw = os.environ.get("WLW_BATCH_TIME_MINUTES")
    if not raw:
        return
    try:
        settings.batch_time_minutes = int(raw)
    except ValueError:
        return


def _apply_engines_override(settings: Settings) -> None:
    """Apply the comma-separated ``WLW_DEFAULT_ENGINES`` override."""
    raw = os.environ.get("WLW_DEFAULT_ENGINES", "")
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    if parsed:
        settings.default_engines = parsed


def _apply_env_overrides(settings: Settings) -> Settings:
    """Override fields on ``settings`` from ``WLW_*`` environment variables.

    Mutates and returns the same ``Settings`` instance for convenience. Each
    supported env var, when present and non-empty, replaces the matching
    field. Invalid ints are silently ignored so a typo in the RunPod console
    doesn't crash the worker on startup.

    Args:
        settings: The ``Settings`` instance to mutate in place.

    Returns:
        The same ``Settings`` instance with env-var overrides applied.
    """
    _apply_string_overrides(settings)
    _apply_int_overrides(settings)
    _apply_optional_int_override(settings)
    eval_cache = os.environ.get("WLW_EVAL_CACHE_ENABLED")
    if eval_cache:
        settings.eval_cache_enabled = _parse_bool(eval_cache)
    _apply_engines_override(settings)
    return settings


def load_settings(path: Optional[Path] = None) -> Settings:
    """Load settings from disk, returning defaults if the file does not exist.

    ``WLW_*`` environment variables, when present, override any value loaded
    from JSON (and supply values when no JSON file exists). This makes the
    worker friendly to containerised deployments where mutating an on-disk
    config file is impractical.

    Args:
        path: Path to the JSON settings file. Defaults to platform data dir.

    Returns:
        A Settings instance populated from the file (or all defaults), with
        any ``WLW_*`` env-var overrides applied on top.
    """
    cfg_path = path or _default_config_path()
    if cfg_path.exists():
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        known = {f.name for f in Settings.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in known}
        settings = Settings(**filtered)
    else:
        settings = Settings()
    settings = _apply_env_overrides(settings)
    settings.api_url = normalize_api_url(settings.api_url)
    return settings


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    """Persist settings to disk as JSON.

    Args:
        settings: The Settings instance to save.
        path: Path to write. Defaults to platform data dir.
    """
    cfg_path = path or _default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
