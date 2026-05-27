"""
Title: move_annotations.py — Single source of truth for SF move-quality badges
Description:
    Maps SF move classifications (brilliant / best / great / excellent /
    good / inaccuracy / mistake / blunder) to the inline annotation symbol
    (!!, !, ?!, ?, ??) and tooltip title rendered next to each move in the
    main-board moves strip and the SF accuracy-card bar segments.

    Consumed server-side by templatetags/games_extras.py (via filters used by
    partials/_move_annotation.html). Exposed client-side as
    window.WoodLeagueMoveAnnotations by analysis.html's extra_js block
    (json_script of this dict + a small init) so JS consumers like
    charts/sfCp.js can read the same payload.

    Adding a new classification: add an entry here and the server-rendered
    badge plus the JS payload pick it up automatically. The card_sf.html
    bar-segment template still hardcodes the symbols (out of scope for #212)
    — keep this dict in sync with that file by hand for now.

Changelog:
    2026-05-26 (#212): Initial — created as part of the moves-strip work.
"""
from __future__ import annotations

ANNOTATIONS: dict[str, dict[str, str]] = {
    "brilliant":  {"symbol": "!!", "title": "Brilliant"},
    "best":       {"symbol": "",   "title": "Best"},
    "great":      {"symbol": "!",  "title": "Great"},
    "excellent":  {"symbol": "",   "title": "Excellent"},
    "good":       {"symbol": "",   "title": "Good"},
    "inaccuracy": {"symbol": "?!", "title": "Inaccuracy"},
    "mistake":    {"symbol": "?",  "title": "Mistake"},
    "blunder":    {"symbol": "??", "title": "Blunder"},
}


def symbol(classification: str | None) -> str:
    """
    Return the annotation symbol for a classification, or "" if none applies.

    Parameters:
        classification (str | None): SF classification label (case-insensitive),
            or None for an unanalyzed move.

    Returns:
        str: The canonical badge symbol (e.g. "?!"), or "" when the
        classification is None, unknown, or one of best/excellent/good
        (which carry no badge by design).
    """
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("symbol", "")


def title(classification: str | None) -> str:
    """
    Return the tooltip title for a classification.

    Parameters:
        classification (str | None): SF classification label (case-insensitive),
            or None for an unanalyzed move.

    Returns:
        str: The human-readable title (e.g. "Inaccuracy"), or the input
        unchanged when unknown (so the user still sees a label rather than
        a blank tooltip), or "" when the classification is None.
    """
    if not classification:
        return ""
    return ANNOTATIONS.get(classification.lower(), {}).get("title", classification)
