"""
Title: time_control_format.py — Human-readable time-control formatter
Description:
    Pure helper that turns parsed (base_seconds, increment_seconds) values
    into a short human label used by the search results table and game
    preview modal. Falls back to a caller-supplied raw string when the
    values are unknown.

Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations


_SECONDS_PER_DAY = 86400
_SECONDS_PER_MINUTE = 60


def _format_daily(base_seconds: int) -> str:
    """Format a daily time control as ``"N day(s) per move"``."""
    days = base_seconds // _SECONDS_PER_DAY
    suffix = "day" if days == 1 else "days"
    return f"{days} {suffix} per move"


def _format_minutes(base_seconds: int, increment_seconds: int) -> str:
    """Format a minute-scale time control as ``"M min"`` or ``"M+I min"``."""
    minutes = base_seconds // _SECONDS_PER_MINUTE
    if increment_seconds == 0:
        return f"{minutes} min"
    return f"{minutes}+{increment_seconds} min"


def _format_seconds(base_seconds: int, increment_seconds: int) -> str:
    """Format a sub-minute time control as ``"B+I sec"``."""
    return f"{base_seconds}+{increment_seconds} sec"


def format_time_control(
    base_seconds: int | None,
    increment_seconds: int | None,
    *,
    raw: str | None = None,
) -> str:
    """Render a time control as a short human-readable label.

    Args:
        base_seconds: Per-game base time (or per-move budget for daily).
        increment_seconds: Increment in seconds; ``None`` for daily formats.
        raw: Optional original chess.com string used as a fallback when
            neither field parsed.

    Returns:
        ``"1 day per move"``, ``"15+10 min"``, ``"3 min"``, ``"30+2 sec"``,
        the raw string if provided, or ``""`` when nothing is parseable.
    """
    if base_seconds is None:
        return raw or ""

    inc = increment_seconds or 0

    if base_seconds >= _SECONDS_PER_DAY and inc == 0:
        return _format_daily(base_seconds)
    if base_seconds >= _SECONDS_PER_MINUTE:
        return _format_minutes(base_seconds, inc)
    return _format_seconds(base_seconds, inc)
