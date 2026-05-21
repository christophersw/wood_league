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


def chips_for_ply(data: GameAnalysisDataV2, ply: int) -> list[dict]:
    """Return up to three move-category chip dicts for the given ply.

    Chips are assembled from:
    - SF classification (kind="sf")
    - LC0 base_severity (kind="lc0_base")
    - LC0 draw_character (kind="lc0_draw", only when the field is populated)

    The ``label`` value preserves original DB casing for display.
    The ``css_label`` value is the lowercase+underscored variant for CSS classes
    (e.g. ``Missed Win`` → ``missed_win``).

    Params:
        data (GameAnalysisDataV2): Full new-schema analysis data for the game.
        ply (int): The ply number to query.  Ply 1 = White's first move.

    Returns:
        List of chip dicts, each with keys:
            kind      (str) — "sf", "lc0_base", or "lc0_draw"
            label     (str) — original casing as stored in the DB
            css_label (str) — lowercase+underscore version for CSS class suffix
            title     (str) — tooltip text shown on hover
        Returns [] when no engine data exists for the requested ply.
    """
    chips: list[dict] = []

    sf_row = next((m for m in data.sf_moves if m.ply == ply), None)
    lc0_row = next((m for m in data.lc0_moves if m.ply == ply), None)

    if sf_row is not None and sf_row.classification:
        chips.append({
            "kind": "sf",
            "label": sf_row.classification,
            "css_label": _css_label(sf_row.classification),
            "title": "Stockfish classification",
        })

    if lc0_row is not None and lc0_row.base_severity:
        chips.append({
            "kind": "lc0_base",
            "label": lc0_row.base_severity,
            "css_label": _css_label(lc0_row.base_severity),
            "title": "LC0 severity (level 1)",
        })

    if lc0_row is not None and lc0_row.draw_character:
        chips.append({
            "kind": "lc0_draw",
            "label": lc0_row.draw_character,
            "css_label": _css_label(lc0_row.draw_character),
            "title": "LC0 character (level 2)",
        })

    return chips
