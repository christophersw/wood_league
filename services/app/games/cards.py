"""
Title: cards.py — Card context builders for the analysis page
Description:
    Pure functions that turn a GameAnalysisDataV2 into the context dict
    each card partial needs. Stays presentation-free — templates do the
    HTML rendering.

    Provides:
      - build_sf_card_context: SF accuracy/ACPL/classification/tooltip context.
      - build_lc0_card_context: LC0 accuracy/WDL/two-level classification/tooltip context.

Changelog:
    2026-05-21 (#186): Initial — SF card builder.
    2026-05-21 (#186): Add build_lc0_card_context with base_severity + draw_character counts.
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

    Values are normalised to lowercase with spaces replaced by underscores
    before matching, so "Missed Win" matches the key "missed_win". This lets
    Django templates access counts via dot notation (e.g. counts.missed_win).

    Params:
        values: Iterable of classification strings (may include None/empty).
        allowed (tuple): The exhaustive set of classification keys to count.
            Keys must already be lowercase with underscores where applicable.

    Returns:
        dict: Mapping from each allowed key to its integer occurrence count.
    """
    out = {c: 0 for c in allowed}
    for v in values:
        if not v:
            continue
        key = v.lower().replace(" ", "_")
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


# Base severity labels emitted by analysis.derivation._calibration._base_severity.
# Title-case strings are lowercased by _counts() before lookup.
_LC0_BASE_SEVERITY = ("best", "excellent", "good", "inaccuracy", "mistake", "blunder")

# Draw-character modifier labels from analysis.derivation._calibration._draw_modifier.
# Keys use underscores so Django templates can access them via dot notation (e.g.
# draw_character_counts.white.missed_win). The worker emits "Missed Win" / "Losing
# Blunder" / "Risky" / "Simplification" (Title Case with spaces); _counts() lowercases
# values before lookup, so we normalize spaces to underscores here and match after
# normalisation in _counts().
_LC0_DRAW_CHARACTER = ("missed_win", "losing_blunder", "risky", "simplification")


def _lc0_wdl_triple(data: GameAnalysisDataV2, side: str) -> dict:
    """Return the game-end WDL probability triple for one side.

    Reads white-side fields from the dataclass directly. Black-side fields are
    not yet surfaced on GameAnalysisDataV2 (they exist on the DB model but were
    not included in the v2 loader); getattr with a None default keeps the card
    rendering gracefully blank.

    Params:
        data (GameAnalysisDataV2): New-schema analysis dataclass.
        side (str): "white" or "black".

    Returns:
        dict with keys win, draw, loss — each a float in [0, 1] or None.
    """
    if side == "white":
        return {
            "win": data.lc0_white_win_prob,
            "draw": data.lc0_white_draw_prob,
            "loss": data.lc0_white_loss_prob,
        }
    return {
        "win": getattr(data, "lc0_black_win_prob", None),
        "draw": getattr(data, "lc0_black_draw_prob", None),
        "loss": getattr(data, "lc0_black_loss_prob", None),
    }


def _lc0_tooltip_meta(data: GameAnalysisDataV2) -> dict:
    """Extract LC0 run metadata for the card info tooltip.

    Params:
        data (GameAnalysisDataV2): New-schema analysis dataclass.

    Returns:
        dict with keys network_name, engine_nodes, contempt,
        draw_rate_reference, calibration_elo, analyzed_at.
    """
    return {
        "network_name": data.lc0_network_name,
        "engine_nodes": data.lc0_engine_nodes,
        "contempt": data.lc0_contempt,
        "draw_rate_reference": data.lc0_draw_rate_reference,
        "calibration_elo": data.lc0_calibration_elo,
        "analyzed_at": data.lc0_analyzed_at,
    }


def _lc0_side_counts(moves: list) -> dict:
    """Build per-side classification counts for one side's LC0 move rows.

    Computes both base-severity and draw-character count dicts plus the avg
    delta-mu for the supplied move list.

    Params:
        moves (list): Filtered list of Lc0MoveRow for one side (white or black).

    Returns:
        dict with keys base_severity, draw_character (each a counts dict),
        and avg_delta_mu (float | None).
    """
    return {
        "base_severity": _counts(
            (m.base_severity for m in moves), _LC0_BASE_SEVERITY
        ),
        "draw_character": _counts(
            (m.draw_character for m in moves), _LC0_DRAW_CHARACTER
        ),
        "avg_delta_mu": _avg([m.delta_mu for m in moves]),
    }


def build_lc0_card_context(data: GameAnalysisDataV2) -> dict:
    """Build the template context dict for the LC0 stat card.

    Exposes per-side accuracy, game-end WDL probabilities, both classification
    levels (base_severity primary bar and draw_character subordinate bar),
    avg Δμ per side, and tooltip metadata.

    Params:
        data (GameAnalysisDataV2): New-schema game analysis data.

    Returns:
        dict with keys:
            lc0_white_accuracy (float | None): White accuracy percentage.
            lc0_black_accuracy (float | None): Black accuracy percentage.
            wdl (dict): Nested {white,black} × {win,draw,loss} game-end WDL
                probabilities (0..1 floats from the aggregate means).
            base_severity_counts (dict): Per-side counts for each base-severity
                label (best/excellent/good/inaccuracy/mistake/blunder).
            draw_character_counts (dict): Per-side counts for each draw-character
                label (missed_win/losing_blunder/risky/simplification).
            avg_delta_mu_white (float | None): Mean per-move Δμ for White plies.
            avg_delta_mu_black (float | None): Mean per-move Δμ for Black plies.
            tooltip_meta (dict): network_name, engine_nodes, contempt,
                draw_rate_reference, calibration_elo, analyzed_at.
    """
    white = _lc0_side_counts([m for m in data.lc0_moves if m.ply % 2 == 1])
    black = _lc0_side_counts([m for m in data.lc0_moves if m.ply % 2 == 0])
    return {
        "lc0_white_accuracy": data.lc0_white_accuracy,
        "lc0_black_accuracy": data.lc0_black_accuracy,
        "wdl": {
            "white": _lc0_wdl_triple(data, "white"),
            "black": _lc0_wdl_triple(data, "black"),
        },
        "base_severity_counts": {
            "white": white["base_severity"],
            "black": black["base_severity"],
        },
        "draw_character_counts": {
            "white": white["draw_character"],
            "black": black["draw_character"],
        },
        "avg_delta_mu_white": white["avg_delta_mu"],
        "avg_delta_mu_black": black["avg_delta_mu"],
        "tooltip_meta": _lc0_tooltip_meta(data),
    }
