"""
Title: cards.py — Card context builders for the analysis page
Description:
    Pure functions that turn a GameAnalysisDataV2 into the context dict
    each card partial needs. Stays presentation-free — templates do the
    HTML rendering.

    Provides:
      - build_sf_card_context: SF accuracy/ACPL/classification/tooltip context.

Changelog:
    2026-05-21 (#186): Initial — SF card builder.
"""
from __future__ import annotations

from statistics import fmean

from games.services_v2 import GameAnalysisDataV2


_SF_CLASSES = (
    "brilliant",
    "best",
    "great",
    "excellent",
    "good",
    "inaccuracy",
    "mistake",
    "blunder",
)


def _counts(values, allowed: tuple) -> dict:
    """Count occurrences of each allowed classification in values.

    Params:
        values: Iterable of classification strings (may include None/empty).
        allowed (tuple): The exhaustive set of classification keys to count.

    Returns:
        dict: Mapping from each allowed key to its integer occurrence count.
    """
    out = {c: 0 for c in allowed}
    for v in values:
        if not v:
            continue
        key = v.lower()
        if key in out:
            out[key] += 1
    return out


def _avg(values: list) -> float | None:
    """Return the mean of all non-None numeric values, or None if the list is empty.

    Params:
        values (list): List of numbers or None entries.

    Returns:
        float | None: Mean of non-None values, or None when no values exist.
    """
    nums = [v for v in values if v is not None]
    return fmean(nums) if nums else None


def build_sf_card_context(data: GameAnalysisDataV2) -> dict:
    """Build the template context dict for the Stockfish stat card.

    Extracts per-side accuracy, ACPL, average Win%-drop, move classification
    counts, and tooltip metadata from a fully-populated GameAnalysisDataV2.

    Params:
        data (GameAnalysisDataV2): New-schema game analysis data.

    Returns:
        dict with keys:
            white_accuracy (float | None): White accuracy percentage.
            black_accuracy (float | None): Black accuracy percentage.
            white_acpl (float | None): White average centipawn loss.
            black_acpl (float | None): Black average centipawn loss.
            classification_counts (dict): Per-side counts for each SF class.
            avg_win_drop_white (float | None): Mean move_win_delta for White.
            avg_win_drop_black (float | None): Mean move_win_delta for Black.
            tooltip_meta (dict): engine_depth and analyzed_at strings.
    """
    white_moves = [m for m in data.sf_moves if m.ply % 2 == 1]
    black_moves = [m for m in data.sf_moves if m.ply % 2 == 0]
    return {
        "white_accuracy": data.sf_white_accuracy,
        "black_accuracy": data.sf_black_accuracy,
        "white_acpl": data.sf_white_acpl,
        "black_acpl": data.sf_black_acpl,
        "classification_counts": {
            "white": _counts((m.classification for m in white_moves), _SF_CLASSES),
            "black": _counts((m.classification for m in black_moves), _SF_CLASSES),
        },
        "avg_win_drop_white": _avg([m.move_win_delta for m in white_moves]),
        "avg_win_drop_black": _avg([m.move_win_delta for m in black_moves]),
        "tooltip_meta": {
            "engine_depth": data.sf_engine_depth,
            "analyzed_at": data.sf_analyzed_at,
        },
    }
