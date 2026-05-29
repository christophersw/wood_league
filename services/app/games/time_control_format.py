"""
Title: time_control_format.py — Human-readable time-control formatter
Description:
    Pure helper that turns parsed (base_seconds, increment_seconds) values
    into a short human label used by the search results table and game
    preview modal. Falls back to a caller-supplied raw string when the
    values are unknown. Also provides format_time_control_label for the
    game detail page header (time-class prefix + body).

Changelog:
    2026-05-20: Initial creation (#162).
    2026-05-29: Add format_time_control_label for game detail header (#226).
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


def format_time_control_label(
    time_class: str | None,
    base_seconds: int | None,
    increment_seconds: int | None,
    *,
    raw: str | None = None,
) -> str:
    """Render a time control with its time-class prefix for the page header.

    Composes the existing :func:`format_time_control` body with a title-cased
    time-class prefix, e.g. ``"Rapid · 10+5 min"`` or ``"Daily · 3 days per
    move"``. When the body is empty (nothing parseable and no ``raw``) the
    result is ``""``; when the class is empty the bare body is returned.

    Args:
        time_class (str | None): Chess.com time class ("rapid", "blitz",
            "daily", …) or None.
        base_seconds (int | None): Per-game base time (or per-move budget
            for daily).
        increment_seconds (int | None): Increment in seconds; None for
            daily formats.
        raw (str | None): Optional original string used as a body fallback.

    Returns:
        str: ``"<Class> · <body>"``, the bare body, or ``""``.
    """
    body = format_time_control(base_seconds, increment_seconds, raw=raw)
    if not body:
        return ""
    cls = (time_class or "").strip()
    return f"{cls.title()} · {body}" if cls else body
