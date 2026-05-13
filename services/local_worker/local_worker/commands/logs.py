"""
Title: logs.py — ``wood-league-worker logs`` command implementation
Description:
    Python-native tail/follow for ``worker.log``.  Works on Windows as well
    as POSIX hosts because we never shell out to a ``tail`` binary.

Changelog:
    2026-05-12: Extracted from cli.py (issue #43 follow-up).
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path

import platformdirs
import typer

from local_worker._shared import console


def _resolve_log_path() -> Path:
    """Return the path to ``worker.log`` honouring ``WLW_LOG_DIR``.

    Returns:
        Absolute path; existence is not guaranteed.
    """
    override = os.environ.get("WLW_LOG_DIR", "").strip()
    base = Path(override) if override else Path(
        platformdirs.user_log_dir("wood-league-worker", "WoodLeague")
    )
    return base / "worker.log"


def _tail_lines(log_path: Path, count: int) -> list[str]:
    """Return the last ``count`` lines of ``log_path`` without a subprocess.

    Uses :class:`collections.deque` so memory usage is bounded by ``count``
    regardless of file size.  Works on every supported platform because no
    external ``tail`` binary is required.

    Args:
        log_path: Path to the log file. Caller must ensure it exists.
        count: Number of trailing lines to retain.

    Returns:
        List of up to ``count`` lines, in original order, each retaining
        any trailing newline so callers can write them verbatim.
    """
    if count <= 0:
        return []
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=count))


def _open_at_tail(log_path: Path):
    """Open ``log_path`` for reading and seek to end-of-file.

    Args:
        log_path: Path to the log file. Missing files yield ``None``.

    Returns:
        An open text file handle positioned at EOF, or ``None`` when the
        file does not exist yet.
    """
    try:
        handle = log_path.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    handle.seek(0, 2)  # jump to EOF
    return handle


def _poll_for_new_data(handle, log_path: Path):
    """Read pending bytes, handling rotation/truncation between polls.

    Args:
        handle: Open file handle previously returned by
            :func:`_open_at_tail`. May be re-opened if the file rotated.
        log_path: Path used to stat the file and detect truncation.

    Returns:
        Tuple of ``(chunk, handle)`` where ``chunk`` is the newly read text
        (possibly empty) and ``handle`` is the live (possibly replaced)
        file handle, or ``None`` if the file vanished.
    """
    chunk = handle.read()
    if chunk:
        return chunk, handle

    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        handle.close()
        return "", None
    if size < handle.tell():
        handle.close()
        handle = log_path.open("r", encoding="utf-8", errors="replace")
    return "", handle


def _follow_log(log_path: Path, initial_tail: int) -> None:
    """Print the last ``initial_tail`` lines, then stream new ones forever.

    A polling loop with ``time.sleep(0.5)`` and ``seek`` replaces ``tail
    -f`` so this works on Windows. Stops cleanly on ``KeyboardInterrupt``.

    Args:
        log_path: Path to the log file. Re-opened each poll cycle so the
            primary ``worker.log`` is picked up after a ``run`` truncates
            and recreates it.
        initial_tail: Number of lines to print up front.
    """
    for line in _tail_lines(log_path, initial_tail):
        sys.stdout.write(line)
    sys.stdout.flush()

    handle = _open_at_tail(log_path)
    try:
        while True:
            if handle is None:
                if not log_path.exists():
                    time.sleep(0.5)
                    continue
                handle = log_path.open("r", encoding="utf-8", errors="replace")

            chunk, handle = _poll_for_new_data(handle, log_path)
            if chunk:
                sys.stdout.write(chunk)
                sys.stdout.flush()
                continue
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        if handle is not None:
            handle.close()


def logs(
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Stream new log lines as they're written."
    ),
    tail: int = typer.Option(
        50, "--tail", "-n", help="How many recent lines to print before following."
    ),
) -> None:
    """Show worker log output.

    With no flags, prints the log file path and the last ``--tail`` lines.
    With ``--follow``, streams new lines as the worker writes them (useful
    in a second terminal while ``run`` is going). Implemented in pure
    Python — no dependency on a Unix ``tail`` binary, so it works on
    Windows too.
    """
    log_path = _resolve_log_path()
    console.print(f"[cyan]Log file:[/] {log_path}")
    if not log_path.exists():
        console.print("[yellow]Log file does not exist yet — run the worker first.")
        return

    if follow:
        _follow_log(log_path, tail)
        return

    try:
        for line in _tail_lines(log_path, tail):
            sys.stdout.write(line)
        sys.stdout.flush()
    except OSError as exc:
        console.print(f"[red]Could not read log: {exc}")
