"""
Title: game_meta.py — Extract human-readable game info from PGN headers
Description:
    Pure helper to pull White/Black player names, Date, and Event from a PGN
    string for display in the worker's live UI. No engine, no mainline parsing.

Changelog:
    2026-05-11: Initial creation (issue #20 follow-up — surface matchup in UI).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import chess.pgn

# PGN placeholders used by exporters when a tag is unknown. Treat them as empty
# so the UI doesn't show "Unknown vs. ?" rows.
_PLACEHOLDER_VALUES = {"", "?", "Unknown", "unknown"}
_DATE_PLACEHOLDER = "????.??.??"
_EVENT_MAX_LEN = 30


@dataclass(frozen=True)
class GameMeta:
    """Human-readable summary of a game's PGN header tags.

    Attributes:
        matchup: "White vs. Black" string, or "" if either side is missing.
        date: PGN [Date] reformatted YYYY-MM-DD if well-formed, raw otherwise,
            "" if the placeholder ????.??.?? was used or the tag was missing.
        event: PGN [Event] tag, truncated to 30 chars, "" if missing/placeholder.
    """

    matchup: str
    date: str
    event: str


def _clean(value: str | None) -> str:
    """Return ``value`` stripped, or "" if it matches a known PGN placeholder."""
    if value is None:
        return ""
    cleaned = value.strip()
    if cleaned in _PLACEHOLDER_VALUES:
        return ""
    return cleaned


def _format_date(raw: str) -> str:
    """Convert PGN ``YYYY.MM.DD`` to ``YYYY-MM-DD``.

    Returns the raw value unchanged if it doesn't match that shape, or "" if
    it's the PGN unknown-date placeholder.
    """
    if not raw or raw == _DATE_PLACEHOLDER:
        return ""
    parts = raw.split(".")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return "-".join(parts)
    return raw


def parse_game_meta(pgn_text: str) -> GameMeta:
    """Parse a PGN string and return its display metadata.

    Args:
        pgn_text: Full PGN string. May be empty or unparseable; in that case
            an all-empty GameMeta is returned rather than raising.

    Returns:
        GameMeta. Missing or placeholder fields are empty strings so callers
        can suppress them in the UI without per-field special casing.
    """
    if not pgn_text:
        return GameMeta(matchup="", date="", event="")

    try:
        headers = chess.pgn.read_headers(io.StringIO(pgn_text))
    except Exception:
        return GameMeta(matchup="", date="", event="")

    if headers is None:
        return GameMeta(matchup="", date="", event="")

    white = _clean(headers.get("White"))
    black = _clean(headers.get("Black"))
    matchup = f"{white} vs. {black}" if white and black else ""

    date = _format_date(_clean(headers.get("Date")))

    event = _clean(headers.get("Event"))
    if len(event) > _EVENT_MAX_LEN:
        event = event[: _EVENT_MAX_LEN - 1] + "…"

    return GameMeta(matchup=matchup, date=date, event=event)
