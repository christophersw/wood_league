"""
Title: config.py — Persistent worker configuration
Description:
    Loads and saves worker settings to a JSON file in the platform-standard
    user data directory. Provides sensible defaults for all settings.

Changelog:
    2026-05-09: Initial creation
"""
from __future__ import annotations

import json
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


def load_settings(path: Optional[Path] = None) -> Settings:
    """Load settings from disk, returning defaults if the file does not exist.

    Args:
        path: Path to the JSON settings file. Defaults to platform data dir.

    Returns:
        A Settings instance populated from the file (or all defaults).
    """
    cfg_path = path or _default_config_path()
    if not cfg_path.exists():
        return Settings()
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    known = {f.name for f in Settings.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in known}
    settings = Settings(**filtered)
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
