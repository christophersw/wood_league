"""Time control formatting service for display-friendly chess time control strings.

Converts standard Chess.com/Lichess time control notation to human-readable format.
"""
from __future__ import annotations


def _seconds_to_human(seconds: int) -> str:
    """Convert seconds to human-readable duration string."""
    if seconds % 86400 == 0:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} min"
    return f"{seconds} sec"


def format_time_control(value: str | None) -> str:
    """Format time control string (base, increment, or correspondence) to human-readable format."""
    if not value:
        return "Unknown"

    raw = value.strip()
    if not raw:
        return "Unknown"

    if raw in {"-", "?"}:
        return raw

    # Daily/correspondence notation, e.g. 1/259200 (one move every 3 days).
    if "/" in raw and ":" not in raw:
        left, right = raw.split("/", 1)
        try:
            moves = int(left)
            seconds = int(right)
            if moves == 1:
                return f"Daily ({_seconds_to_human(seconds)}/move)"
            return f"{moves} moves/{_seconds_to_human(seconds)}"
        except ValueError:
            return raw

    # Increment notation, e.g. 300+2.
    if "+" in raw:
        base, inc = raw.split("+", 1)
        try:
            base_seconds = int(base)
            inc_seconds = int(inc)
            return f"{_seconds_to_human(base_seconds)} + {inc_seconds}s"
        except ValueError:
            return raw

    # Simple base-time notation, e.g. 600.
    try:
        base_seconds = int(raw)
        return _seconds_to_human(base_seconds)
    except ValueError:
        return raw
