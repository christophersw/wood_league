"""
Title: clock_parser.py — Parse %clk annotations from chess.com PGNs
Description:
    Pure-Python parser that extracts per-move time data from chess.com
    PGN move comments. Two modes:

    - Live (bullet/blitz/rapid): %clk is remaining clock; time_spent
      is computed as (previous_clk + increment) - current_clk with
      per-side state.
    - Daily: %clk values are deciseconds rendered as seconds; the
      already-rendered value * 10 equals the inter-move delay in
      seconds (verified empirically — see the spec at
      docs/superpowers/specs/2026-05-11-move-timing-ingest-design.md).

    Negative time deltas (server hiccups, reconnects) are clamped to 0.
    Pre-2020 daily games with no %clk annotations return []; the caller
    can persist game-level fields without per-ply rows.

Changelog:
    2026-05-11: Initial creation (issue #24).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MoveTime:
    """Parsed per-move timing for a single ply.

    Attributes:
        ply: 1-based ply number. ply=1 is White's first move.
        time_spent_ms: Time the player took on this move, in milliseconds.
            Always populated.
        clock_after_ms: Remaining clock after this move, in milliseconds.
            Populated only for live games; None for daily.
    """

    ply: int
    time_spent_ms: int
    clock_after_ms: int | None


_MOVE_RE = re.compile(
    r"""
    (?P<move_no>\d+)        # move number
    (?P<dots>\.+)\s*        # one or three dots
    (?P<san>\S+)\s*         # move SAN
    \{\[\%clk\s+
    (?P<clk>[0-9:.]+)       # H:MM:SS(.ds)
    \]
    """,
    re.VERBOSE,
)


def _clk_to_ms(clk: str) -> int:
    """Convert a `H:MM:SS(.ds)` clock string to milliseconds.

    Args:
        clk: Clock string in H:MM:SS or H:MM:SS.ds format.

    Returns:
        Integer milliseconds equivalent of the clock value.
    """
    h, m, s = clk.split(":")
    return int(int(h) * 3600_000 + int(m) * 60_000 + float(s) * 1000)


def _parse_live(
    matches: list[re.Match],
    base_ms: int,
    increment_ms: int,
) -> list[MoveTime]:
    """Live-game parse: clock deltas with per-side state.

    Args:
        matches: List of regex matches from _MOVE_RE over the PGN.
        base_ms: Starting clock for each side in milliseconds.
        increment_ms: Per-move increment in milliseconds.

    Returns:
        List of MoveTime entries with time_spent_ms and clock_after_ms
        populated. Negative deltas (server hiccups) are clamped to 0.
    """
    prev_clk_white = base_ms
    prev_clk_black = base_ms
    out: list[MoveTime] = []
    for m in matches:
        move_no = int(m.group("move_no"))
        dots = m.group("dots")
        is_black = len(dots) == 3
        ply = move_no * 2 - (0 if is_black else 1)
        clk_after_ms = _clk_to_ms(m.group("clk"))
        prev = prev_clk_black if is_black else prev_clk_white
        spent_ms = (prev + increment_ms) - clk_after_ms
        if spent_ms < 0:
            spent_ms = 0
        if is_black:
            prev_clk_black = clk_after_ms
        else:
            prev_clk_white = clk_after_ms
        out.append(MoveTime(ply=ply, time_spent_ms=spent_ms, clock_after_ms=clk_after_ms))
    return out


def _parse_daily(matches: list[re.Match]) -> list[MoveTime]:
    """Daily-game parse: %clk * 10 = inter-move delay in seconds.

    Chess.com encodes daily game move delays in deciseconds but renders
    them as if they were seconds in the %clk field. Multiplying by 10
    recovers the actual inter-move delay in real seconds.

    Args:
        matches: List of regex matches from _MOVE_RE over the PGN.

    Returns:
        List of MoveTime entries with time_spent_ms populated and
        clock_after_ms set to None (no running clock for daily games).
    """
    out: list[MoveTime] = []
    for m in matches:
        move_no = int(m.group("move_no"))
        dots = m.group("dots")
        is_black = len(dots) == 3
        ply = move_no * 2 - (0 if is_black else 1)
        clk_seconds_decisecond_units = _clk_to_ms(m.group("clk")) / 1000.0
        time_spent_ms = int(clk_seconds_decisecond_units * 10 * 1000)
        out.append(MoveTime(ply=ply, time_spent_ms=time_spent_ms, clock_after_ms=None))
    return out


def parse_move_times(
    pgn: str,
    *,
    time_class: str,
    time_control_base_s: int | None = None,
    time_control_increment_s: int | None = None,
) -> list[MoveTime]:
    """Parse per-move timing from a chess.com PGN.

    Args:
        pgn: Full PGN string.
        time_class: One of 'bullet', 'blitz', 'rapid', 'daily'. Drives the
            parse mode.
        time_control_base_s: Base seconds. Required for live games (used as
            "previous clock" for each side's first move). Ignored for daily.
        time_control_increment_s: Per-move increment in seconds. Defaults to
            0 for live if not supplied. Ignored for daily.

    Returns:
        A list of MoveTime entries, one per ply that carried a %clk
        annotation. Empty list if no %clk annotations are present
        (pre-2020 daily games).
    """
    matches = list(_MOVE_RE.finditer(pgn))
    if not matches:
        return []
    if time_class == "daily":
        return _parse_daily(matches)
    base_ms = (time_control_base_s or 0) * 1000
    increment_ms = (time_control_increment_s or 0) * 1000
    return _parse_live(matches, base_ms, increment_ms)
