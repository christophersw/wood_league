"""
Title: logging_setup.py — Loguru-based logging for the worker
Description:
    Configures loguru sinks for the wood-league-worker CLI. Long-running
    commands (``run``) truncate ``worker.log`` and emit a hardware/driver
    banner at the top of the session. Read-only commands attach to a
    secondary diagnostics sink so the run log is preserved for ``logs``.
    An :class:`_InterceptHandler` bridges stdlib ``logging`` records (used
    by third-party libraries like python-chess, httpx, urllib3) into the
    same loguru sinks as our own logger.

Changelog:
    2026-05-09: Initial creation (stdlib RotatingFileHandler).
    2026-05-12: Rewritten on loguru; added single-session semantics,
        diagnostics side sink, environment banner, intercept handler.
        Closes #43.
"""
from __future__ import annotations

import inspect
import logging
import os
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import platformdirs
from loguru import logger

_LOG_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "{name}:{function}:{line} - {message}"
)

# Loguru level names accepted for ``configure_logging`` / ``--log-level``.
_VALID_LEVELS = {"TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"}


def _log_directory() -> Path:
    """Return the platform-appropriate log directory, creating it if needed.

    Honours the ``WLW_LOG_DIR`` environment variable for tests and packagers.

    Returns:
        Absolute path to the directory in which ``worker.log`` is created.
    """
    override = os.environ.get("WLW_LOG_DIR", "").strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir("wood-league-worker", "WoodLeague")
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def _normalize_level(level: str | int) -> str:
    """Coerce a user-supplied level into a canonical loguru level name.

    Args:
        level: Either a loguru level name (case-insensitive) or an int.

    Returns:
        Upper-case level name. Falls back to ``"INFO"`` for unknown values.
    """
    if isinstance(level, int):
        # Loguru exposes ``level(name)`` only with a name string; map int
        # to the closest standard name via stdlib logging which understands
        # both conventions.
        try:
            name = logging.getLevelName(level)
            if isinstance(name, str) and name.upper() in _VALID_LEVELS:
                return name.upper()
        except Exception:  # noqa: BLE001
            pass
        return "INFO"
    candidate = str(level).strip().upper()
    return candidate if candidate in _VALID_LEVELS else "INFO"


class _InterceptHandler(logging.Handler):
    """Forwards stdlib ``logging`` records into loguru.

    Loguru recommends installing one of these as the root handler so that
    third-party libraries emitting via stdlib ``logging`` (python-chess,
    httpx, urllib3) end up in the same sink and respect the same formatting
    and level threshold as our own logger calls.
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - stdlib API
        """Translate a stdlib ``LogRecord`` into a loguru log call.

        Args:
            record: The stdlib record produced by another library.
        """
        # Map stdlib level to loguru level name, falling back to numeric.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Walk up the stack so loguru reports the originating frame, not
        # this handler. The pattern is taken verbatim from the loguru docs.
        frame: Optional[Any] = inspect.currentframe()
        depth = 0
        while frame is not None:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _install_intercept_handler(level: str) -> None:
    """Replace the stdlib root handlers with a single :class:`_InterceptHandler`.

    Args:
        level: Threshold to apply to the stdlib root logger; loguru sinks
            still apply their own level filters on top of this.
    """
    handler = _InterceptHandler()
    logging.basicConfig(handlers=[handler], level=0, force=True)
    logging.getLogger().setLevel(getattr(logging, level, logging.INFO))


def configure_logging(level: str = "INFO", reset_file: bool = False) -> Path:
    """Install loguru sinks for this CLI invocation.

    Args:
        level: Threshold for the primary file sink. Accepts loguru level
            names (``TRACE``/``DEBUG``/``INFO``/``WARNING``/``ERROR``/
            ``CRITICAL``) — case-insensitive.
        reset_file: If ``True``, truncate ``worker.log`` before opening it.
            Long-running commands (``run``) pass ``True``; read-only
            commands pass ``False`` so the previous session's log is
            preserved and a separate ``worker.diagnostics.log`` captures
            any warnings raised by the read-only command itself.

    Returns:
        Path to ``worker.log`` (the primary, human-readable session log).
    """
    normalized = _normalize_level(level)
    log_dir = _log_directory()
    log_file = log_dir / "worker.log"
    diagnostics_file = log_dir / "worker.diagnostics.log"

    # Tear down any previously installed sinks so repeated invocations in
    # the same process (e.g. tests) start from a clean slate.
    logger.remove()

    if reset_file:
        # Single-session semantics: blow away the previous run's file.
        try:
            log_file.unlink(missing_ok=True)
        except OSError:
            # Permission errors etc. — degrade gracefully; loguru will
            # surface the failure when it tries to open the sink below.
            pass
        logger.add(
            log_file,
            level=normalized,
            format=_LOG_FORMAT,
            mode="w",
            encoding="utf-8",
            enqueue=False,
        )
    else:
        # Read-only commands: do not touch worker.log. Capture our own
        # warnings to a small side sink with built-in rotation so it can
        # never grow unbounded.
        logger.add(
            diagnostics_file,
            level="WARNING",
            format=_LOG_FORMAT,
            rotation="1 MB",
            retention=1,
            encoding="utf-8",
            enqueue=False,
        )

    _install_intercept_handler(normalized)
    return log_file


def _safe_call(func: Any) -> Any:
    """Call ``func`` and return its value, or ``"unknown"`` on any error.

    Args:
        func: Zero-argument callable used to probe one environment field.

    Returns:
        The function's return value, or the string ``"unknown"`` if the
        call raised any exception. Used by :func:`_detect_environment`
        to keep banner generation total even when one probe fails.
    """
    try:
        return func()
    except Exception:  # noqa: BLE001 - banner must never crash startup
        return "unknown"


def _detect_torch() -> dict[str, Any]:
    """Probe for PyTorch and its GPU/MPS support.

    Returns:
        Mapping with keys ``available``, ``version``, ``cuda``, ``mps``,
        and ``gpus``. ``available`` is ``False`` when torch is not
        installed; the other fields fall back to safe defaults.
    """
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001
        return {"available": False, "version": None, "cuda": False, "mps": False, "gpus": []}

    cuda = bool(getattr(torch.cuda, "is_available", lambda: False)())
    mps = bool(
        getattr(getattr(torch.backends, "mps", None), "is_available", lambda: False)()
    )
    gpus: list[str] = []
    if cuda:
        try:
            count = int(torch.cuda.device_count())
            gpus = [str(torch.cuda.get_device_name(i)) for i in range(count)]
        except Exception:  # noqa: BLE001
            gpus = []
    return {
        "available": True,
        "version": getattr(torch, "__version__", "unknown"),
        "cuda": cuda,
        "mps": mps,
        "gpus": gpus,
    }


def _probe_engine_version(binary: str | None, args: tuple[str, ...]) -> str:
    """Run ``binary args`` once and return the first line of output.

    Args:
        binary: Absolute path to an engine binary, or ``None``.
        args: Argument tuple (e.g. ``("--version",)``) to pass to it.

    Returns:
        Short version string suitable for the banner, or ``"unknown"`` if
        the binary is missing or refuses to report a version quickly.
    """
    if not binary:
        return "unknown"
    import subprocess  # local import keeps cold-import cost down

    try:
        result = subprocess.run(  # noqa: S603 - args are constants
            [binary, *args], capture_output=True, text=True, timeout=3
        )
        line = (result.stdout or result.stderr).strip().splitlines()
        return line[0] if line else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _detect_environment() -> dict[str, Any]:
    """Probe host OS, runtime, accelerators, engine binaries, and tablebases.

    All OS calls go through small helpers so the banner stays total even
    when one probe fails. The result is a flat-ish dict consumed by
    :func:`log_session_banner` and (optionally) by the telemetry tags.

    Returns:
        Dict containing host, python, torch, gpus, engines, and syzygy keys.
    """
    host = {
        "system": _safe_call(platform.system),
        "release": _safe_call(platform.release),
        "machine": _safe_call(platform.machine),
    }
    python_info = {
        "version": _safe_call(platform.python_version),
        "implementation": _safe_call(platform.python_implementation),
    }
    torch_info = _detect_torch()

    stockfish_path = shutil.which("stockfish")
    lc0_path = shutil.which("lc0")
    engines = {
        "stockfish": {
            "path": stockfish_path,
            "version": _probe_engine_version(stockfish_path, ("--help",))
            if stockfish_path
            else "not found",
        },
        "lc0": {
            "path": lc0_path,
            "version": _probe_engine_version(lc0_path, ("--version",))
            if lc0_path
            else "not found",
        },
    }

    return {
        "host": host,
        "python": python_info,
        "torch": torch_info,
        "engines": engines,
    }


def _format_banner_lines(env: dict[str, Any], log_file: Path) -> list[str]:
    """Render :func:`_detect_environment` output into human-readable lines.

    Args:
        env: Mapping returned by :func:`_detect_environment`.
        log_file: Primary log file path; used to derive an associated
            Syzygy tablebase directory probe (best-effort).

    Returns:
        List of banner lines, ready to be emitted one per ``logger.info``.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        try:
            release = _pkg_version("wood-league-worker")
        except PackageNotFoundError:
            release = "source"
    except Exception:  # noqa: BLE001
        release = "unknown"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    host = env.get("host", {})
    python_info = env.get("python", {})
    torch_info = env.get("torch", {})
    engines = env.get("engines", {})

    if torch_info.get("available"):
        torch_line = (
            f"torch: {torch_info.get('version', 'unknown')}  "
            f"cuda={torch_info.get('cuda', False)}  "
            f"mps={torch_info.get('mps', False)}"
        )
    else:
        torch_line = "torch: not installed"

    gpus = torch_info.get("gpus", []) or []
    mps_note = "mps available" if torch_info.get("mps") else "no gpu"
    gpus_line = f"gpus: {gpus or '[]'}  ({mps_note})"

    engine_bits = []
    for name, info in engines.items():
        if info.get("path"):
            engine_bits.append(
                f"{name} {info.get('version', 'unknown')} @ {info['path']}"
            )
        else:
            engine_bits.append(f"{name} not found")
    engines_line = "engines: " + "; ".join(engine_bits)

    # Best-effort Syzygy probe: look adjacent to the log dir's parent for
    # the conventional install location. Failures degrade to "unknown".
    syzygy_dir = log_file.parent.parent / "syzygy"
    if syzygy_dir.exists() and syzygy_dir.is_dir():
        try:
            files = list(syzygy_dir.iterdir())
            wdl = sum(1 for f in files if f.suffix == ".rtbw")
            dtz = sum(1 for f in files if f.suffix == ".rtbz")
            syzygy_line = (
                f"syzygy: wdl={wdl} dtz={dtz} files at {syzygy_dir}"
            )
        except OSError:
            syzygy_line = f"syzygy: present at {syzygy_dir} (unreadable)"
    else:
        syzygy_line = "syzygy: not configured"

    return [
        f"=== wood-league-worker {release} — session {now} ===",
        (
            f"host: {host.get('system', 'unknown')} "
            f"{host.get('machine', 'unknown')} "
            f"{host.get('release', 'unknown')} / "
            f"Python {python_info.get('version', 'unknown')}"
        ),
        torch_line,
        gpus_line,
        engines_line,
        syzygy_line,
    ]


def log_session_banner(log_file: Path) -> None:
    """Emit the hardware/driver/engine banner at the top of a fresh session.

    Called exactly once, immediately after
    ``configure_logging(reset_file=True)`` succeeds. Failures probing any
    single field degrade to ``"unknown"`` rather than aborting the banner.

    Args:
        log_file: The path returned by :func:`configure_logging`; used to
            locate adjacent resources (e.g. Syzygy directory) for the
            banner's last line.
    """
    env = _detect_environment()
    for line in _format_banner_lines(env, log_file):
        logger.info(line)


__all__ = [
    "configure_logging",
    "log_session_banner",
    "_detect_environment",
    "_InterceptHandler",
]
