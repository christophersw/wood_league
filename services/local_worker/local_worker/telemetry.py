"""
Title: telemetry.py — Opt-in remote diagnostics for the worker (GlitchTip)
Description:
    Thin wrapper around ``sentry-sdk`` pointed at a self-hosted GlitchTip
    instance (Sentry-API-compatible). All functions are no-ops unless the
    user has explicitly opted in via :func:`prompt_for_consent` or the
    ``telemetry enable`` CLI subcommand.

    Consent is persisted to a small JSON file in the user's config
    directory (``platformdirs.user_config_dir``) — separate from the
    main ``settings.json`` so that nuking it does not erase API keys.

Changelog:
    2026-05-12: Initial creation. Closes #43.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Optional

import platformdirs

# Baked-in default DSN, intentionally empty until GlitchTip is provisioned.
# Override at runtime via ``WOOD_LEAGUE_GLITCHTIP_DSN`` or by editing the
# constant in a release build. An empty value disables telemetry entirely.
_DEFAULT_GLITCHTIP_DSN: str = (
    "https://9c91de7f2d714cb38c232a9947261f82@glitchtip-web-production-944c.up.railway.app/1"
)
_CONSENT_PROMPT = (
    "Help debug worker issues by sending anonymous diagnostics "
    "(errors, hardware info) to GlitchTip? [y/N]: "
)


def default_config_path() -> Path:
    """Return the path to the worker's auxiliary JSON config file.

    This is distinct from ``settings.json`` (in the user-data directory):
    consent lives in user-config so wiping caches/data never silently
    re-enables telemetry.

    Returns:
        Absolute path to ``config.json``; parent directory is created.
    """
    base = Path(platformdirs.user_config_dir("wood-league-worker", "WoodLeague"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "config.json"


def _read_config(config_path: Path) -> dict[str, Any]:
    """Read the JSON config file, returning ``{}`` if it is missing/corrupt.

    Args:
        config_path: Path to ``config.json``.

    Returns:
        Parsed config dict. Always safe to mutate and write back.
    """
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_config(config_path: Path, data: dict[str, Any]) -> None:
    """Persist the JSON config file atomically-ish.

    Args:
        config_path: Path to ``config.json``.
        data: Full dict to serialise. Indented for human readability.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_consent(config_path: Optional[Path] = None) -> Optional[bool]:
    """Return the previously-recorded consent value, or ``None`` if never set.

    Args:
        config_path: Optional override for tests. Defaults to
            :func:`default_config_path`.

    Returns:
        ``True``/``False`` if the user has answered the consent prompt,
        otherwise ``None`` to signal "ask again on next eligible run".
    """
    data = _read_config(config_path or default_config_path())
    value = data.get("telemetry")
    if isinstance(value, bool):
        return value
    return None


def set_consent(config_path: Path, value: bool) -> None:
    """Persist a new consent value.

    Used by ``wood-league-worker telemetry enable`` and
    ``... telemetry disable`` to update the choice without prompting.

    Args:
        config_path: Path to ``config.json`` (typically
            :func:`default_config_path`).
        value: ``True`` to opt in, ``False`` to opt out.
    """
    data = _read_config(config_path)
    data["telemetry"] = bool(value)
    data["asked_at"] = datetime.now(timezone.utc).isoformat()
    _write_config(config_path, data)


def prompt_for_consent(config_path: Path) -> bool:
    """First-run interactive consent prompt.

    Reads the persisted value if it already exists. Otherwise reads one
    line from stdin, treats ``y``/``yes`` (case-insensitive) as opt-in,
    and persists the answer alongside an ISO ``asked_at`` timestamp.

    Args:
        config_path: Path to ``config.json``.

    Returns:
        Effective consent value (``True``/``False``).
    """
    existing = get_consent(config_path)
    if existing is not None:
        return existing

    # ``input`` is intentional — questionary is overkill for one y/N prompt
    # and would force an interactive TTY where a piped CI install does not
    # have one. EOFError on a closed stdin defaults to "no".
    try:
        raw = input(_CONSENT_PROMPT)
    except EOFError:
        raw = ""
    consent = raw.strip().lower() in {"y", "yes"}
    set_consent(config_path, consent)
    return consent


def _resolve_dsn(dsn: Optional[str]) -> str:
    """Resolve the effective DSN, considering env var and baked-in default.

    Args:
        dsn: Explicit DSN from the caller, if any. Wins over everything.

    Returns:
        DSN string. Empty string means "telemetry disabled".
    """
    if dsn:
        return dsn.strip()
    env_dsn = os.environ.get("WOOD_LEAGUE_GLITCHTIP_DSN", "").strip()
    if env_dsn:
        return env_dsn
    return _DEFAULT_GLITCHTIP_DSN.strip()


def _hash_worker_id(worker_id: str) -> str:
    """Return the first 12 chars of the SHA-256 of ``worker_id``.

    Args:
        worker_id: The install token / configured worker_id.

    Returns:
        12-char hex prefix, or the string ``"anonymous"`` if empty.
    """
    if not worker_id:
        return "anonymous"
    return sha256(worker_id.encode("utf-8", errors="ignore")).hexdigest()[:12]


class _SentryLogsBridge(logging.Handler):
    """Forward stdlib ``logging`` records to :data:`sentry_sdk.logger`.

    Sentry's experimental ``enable_logs`` transport ships records that go
    through ``sentry_sdk.logger`` as structured log entries visible in the
    Logs view. Existing worker code uses ``logging.getLogger(__name__)``;
    this bridge translates each record to the equivalent
    ``sentry_sdk.logger`` call without touching callsites.
    """

    _LEVEL_MAP = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warning",
        logging.ERROR: "error",
        logging.CRITICAL: "fatal",
    }

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - stdlib API
        """Send one record to ``sentry_sdk.logger`` at the matching level.

        Args:
            record: The stdlib record produced anywhere in the process.
        """
        try:
            import sentry_sdk
        except ImportError:  # pragma: no cover - sentry-sdk is a hard dep
            return
        level_name = self._LEVEL_MAP.get(record.levelno, "info")
        method = getattr(sentry_sdk.logger, level_name, None)
        if method is None:  # pragma: no cover - level map covers stdlib levels
            return
        try:
            method(record.getMessage(), logger=record.name)
        except Exception:  # noqa: BLE001 - never let logging crash the worker
            return


def _install_structured_logs_bridge() -> None:
    """Attach :class:`_SentryLogsBridge` to the stdlib root logger once.

    Idempotent: re-running init_telemetry does not duplicate handlers.
    """
    root = logging.getLogger()
    if any(isinstance(h, _SentryLogsBridge) for h in root.handlers):
        return
    handler = _SentryLogsBridge()
    handler.setLevel(logging.INFO)
    root.addHandler(handler)


def init_telemetry(
    consent: bool,
    release: str,
    dsn: Optional[str] = None,
    environment_info: Optional[dict[str, Any]] = None,
    worker_id: str = "",
) -> bool:
    """Initialise ``sentry-sdk`` against GlitchTip.

    No-op when ``consent`` is ``False`` or when the resolved DSN is empty.
    Wires up :class:`sentry_sdk.integrations.logging.LoggingIntegration`
    so ``INFO`` records become breadcrumbs and ``WARNING``+ records are
    reported as events. Also enables the experimental ``enable_logs``
    transport and attaches a stdlib-logging bridge that forwards every
    record to :data:`sentry_sdk.logger` so ordinary
    ``logging.getLogger(__name__).info(...)`` calls show up in the
    GlitchTip log explorer during normal (no-error) operation.

    Args:
        consent: Whether the user has opted in. ``False`` short-circuits
            to a no-op.
        release: Version string applied as the Sentry ``release`` tag.
        dsn: Optional explicit DSN override. Defaults to the
            ``WOOD_LEAGUE_GLITCHTIP_DSN`` env var, then to
            :data:`_DEFAULT_GLITCHTIP_DSN`.
        environment_info: Optional output of
            ``logging_setup._detect_environment()`` used to tag the event
            with host/python/engine details.
        worker_id: Raw worker identifier; only its hashed prefix is sent.

    Returns:
        ``True`` if telemetry was initialised, ``False`` otherwise.
    """
    if not consent:
        return False

    resolved = _resolve_dsn(dsn)
    if not resolved:
        return False

    # Local imports keep ``import local_worker.telemetry`` cheap when
    # consent is off (no sentry_sdk attached to module init).
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=resolved,
        release=release,
        integrations=[
            # INFO breadcrumbs, WARNING+ events. Breadcrumbs alone aren't
            # transmitted; the bridge below ships INFO+ as structured logs.
            LoggingIntegration(level=20, event_level=30),
        ],
        send_default_pii=False,
        traces_sample_rate=0.0,
        _experiments={"enable_logs": True},
    )
    _install_structured_logs_bridge()

    sentry_sdk.set_tag("worker_id", _hash_worker_id(worker_id))
    if environment_info:
        host = environment_info.get("host", {})
        python_info = environment_info.get("python", {})
        engines = environment_info.get("engines", {})
        sentry_sdk.set_tag("os", str(host.get("system", "unknown")))
        sentry_sdk.set_tag("arch", str(host.get("machine", "unknown")))
        sentry_sdk.set_tag("python", str(python_info.get("version", "unknown")))
        installed = sorted(name for name, info in engines.items() if info.get("path"))
        sentry_sdk.set_tag("engines", ",".join(installed) or "none")

    return True


__all__ = [
    "default_config_path",
    "get_consent",
    "set_consent",
    "prompt_for_consent",
    "init_telemetry",
]
