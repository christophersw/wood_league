"""
Title: time_control_parser.py — Parse chess.com time_control strings
Description:
    Pure helper that converts chess.com's `time_control` string field
    into structured (base_seconds, increment_seconds) values. Returns
    (None, None) for unrecognised input so callers can store NULLs.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from __future__ import annotations


def parse_time_control(time_control: str) -> tuple[int | None, int | None]:
    """Parse a chess.com `time_control` string.

    Args:
        time_control: Raw string from the chess.com API. Known shapes:
            - "180"        — live, 3 minute, no increment
            - "180+0"      — live, 3 minute, explicit zero increment
            - "600+5"      — live, 10 minute with 5s increment
            - "1/259200"   — daily, one move per 259200 seconds (3 days)

    Returns:
        Tuple of (base_seconds, increment_seconds). For daily formats the
        base is the per-move budget and increment is None. For unknown or
        empty input, returns (None, None).
    """
    if not time_control:
        return (None, None)
    if time_control.startswith("1/"):
        try:
            return (int(time_control[2:]), None)
        except ValueError:
            return (None, None)
    if "+" in time_control:
        base_str, inc_str = time_control.split("+", 1)
        try:
            return (int(base_str), int(inc_str))
        except ValueError:
            return (None, None)
    try:
        return (int(time_control), 0)
    except ValueError:
        return (None, None)
