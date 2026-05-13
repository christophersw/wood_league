"""
Title: banner.py — Session-banner line formatters
Description:
    Renders the multi-line hardware/runtime banner emitted at the top of a
    fresh ``worker.log`` session. Split out of
    :mod:`local_worker.logging_setup` so each module stays comfortably
    under the Halstead-effort quality gate.

Changelog:
    2026-05-12: Extracted from logging_setup.py (issue #43 follow-up).
    2026-05-12: lc0 backend default surfaced in the engines line (issue #54).
    2026-05-12: Syzygy banner now reads ``Settings.syzygy_path`` from the
        worker config instead of guessing a sibling directory (issue #54).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from local_worker.config import load_settings


def _resolve_release() -> str:
    """Look up the installed package version for the banner header.

    Returns:
        The PyPI release string, ``"source"`` for editable installs, or
        ``"unknown"`` if even the metadata import machinery fails.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version as _pkg_version

        try:
            return _pkg_version("wood-league-worker")
        except PackageNotFoundError:
            return "source"
    except Exception:  # noqa: BLE001
        return "unknown"


def _header_line(release: str) -> str:
    """Render the top banner line containing release and timestamp.

    Args:
        release: Release string from :func:`_resolve_release`.

    Returns:
        Single header line.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"=== wood-league-worker {release} — session {now} ==="


def _host_line(host: dict[str, Any], python_info: dict[str, Any]) -> str:
    """Render the host/python identification banner line.

    Args:
        host: ``env['host']`` mapping (system/machine/release).
        python_info: ``env['python']`` mapping (version/implementation).

    Returns:
        A single ``host: ...`` banner line.
    """
    return (
        f"host: {host.get('system', 'unknown')} "
        f"{host.get('machine', 'unknown')} "
        f"{host.get('release', 'unknown')} / "
        f"Python {python_info.get('version', 'unknown')}"
    )


def _torch_line(torch_info: dict[str, Any]) -> str:
    """Render the ``torch:`` banner line.

    Args:
        torch_info: ``env['torch']`` mapping.

    Returns:
        Either a populated ``torch: <ver>`` line or
        ``"torch: not installed"`` when PyTorch is missing.
    """
    if not torch_info.get("available"):
        return "torch: not installed"
    return (
        f"torch: {torch_info.get('version', 'unknown')}  "
        f"cuda={torch_info.get('cuda', False)}  "
        f"mps={torch_info.get('mps', False)}"
    )


def _gpus_line(torch_info: dict[str, Any]) -> str:
    """Render the GPU summary banner line.

    Args:
        torch_info: ``env['torch']`` mapping.

    Returns:
        A single ``gpus: ...`` banner line including an MPS/no-GPU note.
    """
    gpus = torch_info.get("gpus", []) or []
    mps_note = "mps available" if torch_info.get("mps") else "no gpu"
    return f"gpus: {gpus or '[]'}  ({mps_note})"


def _engines_line(engines: dict[str, Any]) -> str:
    """Render the chess-engine inventory banner line.

    Args:
        engines: ``env['engines']`` mapping; each value has ``path`` and
            ``version`` keys (or ``path is None`` when not found).

    Returns:
        A single ``engines: ...`` line.
    """
    engine_bits: list[str] = []
    for name, info in engines.items():
        if info.get("path"):
            backend = info.get("backend")
            suffix = f" backend={backend}" if backend else ""
            engine_bits.append(
                f"{name} {info.get('version', 'unknown')} @ {info['path']}{suffix}"
            )
        else:
            engine_bits.append(f"{name} not found")
    return "engines: " + "; ".join(engine_bits)


def _resolve_syzygy_dir() -> Path | None:
    """Return the configured Syzygy directory from worker settings, if any.

    Reads ``Settings.syzygy_path`` (the canonical key written by the
    ``configure`` command) and returns it as a ``Path`` when both set and
    existing on disk.

    Returns:
        The configured directory, or ``None`` when unset, blank, or
        missing. Returns ``None`` on any settings-load failure so the
        banner stays total.
    """
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - banner must never crash startup
        return None
    raw = (settings.syzygy_path or "").strip()
    if not raw:
        return None
    try:
        candidate = Path(raw).expanduser()
    except Exception:  # noqa: BLE001
        return None
    if not (candidate.exists() and candidate.is_dir()):
        return None
    return candidate


def _syzygy_line(log_file: Path) -> str:  # noqa: ARG001 - kept for API compat
    """Render the Syzygy tablebase summary banner line.

    Reads the canonical ``syzygy_path`` setting from the worker config; if
    that directory exists and contains any ``.rtbw`` or ``.rtbz`` files,
    the banner reports those counts. Otherwise the banner says
    ``not configured``.

    Args:
        log_file: Primary log file path. Retained for API compatibility
            with earlier banner versions; no longer consulted.

    Returns:
        A single ``syzygy: ...`` banner line.
    """
    syzygy_dir = _resolve_syzygy_dir()
    if syzygy_dir is None:
        return "syzygy: not configured"
    try:
        files = list(syzygy_dir.iterdir())
    except OSError:
        return f"syzygy: present at {syzygy_dir} (unreadable)"
    wdl = sum(1 for f in files if f.suffix == ".rtbw")
    dtz = sum(1 for f in files if f.suffix == ".rtbz")
    if wdl == 0 and dtz == 0:
        return f"syzygy: not configured (no .rtbw/.rtbz at {syzygy_dir})"
    return f"syzygy: wdl={wdl} dtz={dtz} files at {syzygy_dir}"


def format_banner_lines(env: dict[str, Any], log_file: Path) -> list[str]:
    """Render :func:`local_worker.environment.detect_environment` output.

    Args:
        env: Mapping returned by ``detect_environment``.
        log_file: Primary log file path.

    Returns:
        List of banner lines, ready to be emitted one per ``logger.info``.
    """
    torch_info = env.get("torch", {})
    return [
        _header_line(_resolve_release()),
        _host_line(env.get("host", {}), env.get("python", {})),
        _torch_line(torch_info),
        _gpus_line(torch_info),
        _engines_line(env.get("engines", {})),
        _syzygy_line(log_file),
    ]


__all__ = ["format_banner_lines"]
