"""
Title: consent.py — Worker log-upload consent persistence
Description:
    Stores the user's "may we upload session logs?" choice in a small
    JSON file inside the platform user-config directory. Replaces the
    previous GlitchTip telemetry consent flag. Reads the legacy
    ``telemetry`` key for one release so an existing opt-in keeps working
    after upgrade; writes only the new ``log_upload_consent`` key.

Changelog:
    2026-05-13 (#52): Initial creation. Supersedes ``telemetry.py``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import platformdirs

_NEW_KEY = 'log_upload_consent'
_LEGACY_KEY = 'telemetry'

_CONSENT_PROMPT = (
    'Allow the worker to upload its session log to Wood League when '
    'something goes wrong, so the maintainers can help debug? [y/N]: '
)
_CONSENT_HELP = (
    'Logs include each move analysed, engine output, your hashed worker id, '
    'and absolute paths under your home directory. They never include your '
    'API key, your games, or the contents of analysed positions. Uploads are '
    'only viewable by the project maintainers via the admin site.'
)


def default_config_path() -> Path:
    """Return the platform-standard path to ``config.json``.

    Returns:
        Absolute path to the consent config file. Parent dir is created.
    """
    base = Path(platformdirs.user_config_dir('wood-league-worker', 'WoodLeague'))
    base.mkdir(parents=True, exist_ok=True)
    return base / 'config.json'


def _read(config_path: Path) -> dict[str, Any]:
    """Return the parsed config dict, or ``{}`` when missing/corrupt.

    Args:
        config_path: Path to ``config.json``.

    Returns:
        Parsed dict (safe to mutate).
    """
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(config_path: Path, data: dict[str, Any]) -> None:
    """Persist the JSON config file with indented formatting.

    Args:
        config_path: Path to ``config.json``.
        data: Full dict to serialise.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2), encoding='utf-8')


def get_consent(config_path: Optional[Path] = None) -> Optional[bool]:
    """Return the recorded consent value (or ``None`` if never set).

    Reads the new ``log_upload_consent`` key first; falls back to the
    legacy ``telemetry`` key so workers upgrading from 0.4.x keep their
    prior choice.

    Args:
        config_path: Optional override for tests.

    Returns:
        ``True``/``False`` if the user has answered, otherwise ``None``.
    """
    data = _read(config_path or default_config_path())
    value = data.get(_NEW_KEY)
    if isinstance(value, bool):
        return value
    legacy = data.get(_LEGACY_KEY)
    if isinstance(legacy, bool):
        return legacy
    return None


def set_consent(config_path: Path, value: bool) -> None:
    """Persist a new consent value under the canonical key.

    Args:
        config_path: Path to ``config.json``.
        value: ``True`` to opt in, ``False`` to opt out.
    """
    data = _read(config_path)
    data[_NEW_KEY] = bool(value)
    data['asked_at'] = datetime.now(timezone.utc).isoformat()
    # Drop the legacy key so we never end up with two sources of truth.
    data.pop(_LEGACY_KEY, None)
    _write(config_path, data)


def prompt_for_consent(config_path: Path) -> bool:
    """First-run interactive consent prompt.

    Reads the persisted value if it already exists. Otherwise reads one
    line from stdin: ``y``/``yes`` opts in, ``?`` prints the expanded
    privacy notice and re-prompts, anything else opts out.

    Args:
        config_path: Path to ``config.json``.

    Returns:
        Effective consent value.
    """
    existing = get_consent(config_path)
    if existing is not None:
        return existing
    while True:
        try:
            raw = input(_CONSENT_PROMPT)
        except EOFError:
            raw = ''
        answer = raw.strip().lower()
        if answer == '?':
            print(_CONSENT_HELP)
            continue
        consent = answer in {'y', 'yes'}
        set_consent(config_path, consent)
        return consent


__all__ = [
    'default_config_path',
    'get_consent',
    'set_consent',
    'prompt_for_consent',
]
