"""
Title: chip_data.py — Build the per-ply move-category chip strip
Description:
    Returns up to three chips for a given ply: the Stockfish move
    classification, the LC0 base severity, and (when populated) the LC0
    draw character. Each chip is a plain dict suitable for the
    ``_move_chips.html`` partial.

    The function is intentionally pure — it does not touch the database.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

from games.services_v2 import GameAnalysisDataV2


def _css_label(label: str) -> str:
    """Convert a label string to a CSS-safe suffix (lowercase, spaces→underscores).

    Params:
        label (str): Original DB label, e.g. "Missed Win" or "blunder".

    Returns:
        CSS-safe string, e.g. "missed_win" or "blunder".
    """
    return label.lower().replace(" ", "_")


def _chip(kind: str, label: str | None, title: str) -> dict | None:
    """Build one chip dict, or None when ``label`` is empty/None."""
    if not label:
        return None
    return {
        "kind": kind,
        "label": label,
        "css_label": _css_label(label),
        "title": title,
    }


def chips_for_ply(data: GameAnalysisDataV2, ply: int) -> list[dict]:
    """Return up to three move-category chip dicts for the given ply.

    Chips: SF classification, LC0 base_severity, LC0 draw_character (only when
    populated). ``label`` preserves DB casing; ``css_label`` is the lowercase+
    underscored variant for CSS class suffixes (e.g. ``Missed Win`` →
    ``missed_win``).

    Params:
        data (GameAnalysisDataV2): Full new-schema analysis data for the game.
        ply (int): The ply number to query. Ply 1 = White's first move.

    Returns:
        List of chip dicts (possibly empty). Each dict has keys ``kind``,
        ``label``, ``css_label``, ``title``.
    """
    sf_row = next((m for m in data.sf_moves if m.ply == ply), None)
    lc0_row = next((m for m in data.lc0_moves if m.ply == ply), None)
    candidates = [
        _chip("sf", sf_row.classification if sf_row else None, "Stockfish classification"),
        _chip("lc0_base", lc0_row.base_severity if lc0_row else None, "LC0 severity (level 1)"),
        _chip("lc0_draw", lc0_row.draw_character if lc0_row else None, "LC0 character (level 2)"),
    ]
    return [c for c in candidates if c is not None]
