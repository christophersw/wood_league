"""
Title: chart_data.py — JSON-shape builders for the analysis charts
Description:
    Each function returns a list of small dicts that the corresponding
    chart partial dumps via json_script. No HTML, no Plotly.

Changelog:
    2026-05-21 (#186): Initial.
    2026-05-27 (#216): lc0_wdl_payload emits per-ply ``classification`` key.
    2026-05-27 (#216): Task 8 — retire winpct_payload (Win-for-White chart removed).
    2026-05-29 (#226): sf_cp_payload and lc0_wdl_payload emit per-ply ``book`` flag.
"""
from __future__ import annotations

from games.services_v2 import GameAnalysisDataV2


def sf_cp_payload(data: GameAnalysisDataV2) -> list[dict]:
    """Build the Stockfish centipawn chart payload.

    Each entry carries the White-frame cp_eval, mate_in, classification,
    SAN, and a ``book`` flag indicating whether the move falls within
    the opening book (ply <= data.book_ply_count).

    Params:
        data: GameAnalysisDataV2 — the analysed game.

    Returns:
        list[dict]: One dict per analysed move, keys ``ply``, ``cp_eval``,
        ``mate_in``, ``classification``, ``san``, ``book``.
    """
    return [
        {
            "ply": m.ply,
            "cp_eval": m.cp_eval,
            "mate_in": m.mate_in,
            "classification": (m.classification or "").lower(),
            "san": m.san,
            "book": m.ply <= data.book_ply_count,
        }
        for m in data.sf_moves
    ]


def lc0_wdl_payload(data: GameAnalysisDataV2) -> list[dict]:
    """Build the LC0 WDL chart payload.

    Each entry carries the White-frame WDL triple plus the per-move
    base-severity classification used by the bottom-of-chart classification
    strip in lc0Wdl.js.

    Params:
        data: GameAnalysisDataV2 — the analysed game.

    Returns:
        list[dict]: One dict per analysed move, keys ``ply``, ``wdl_win``,
        ``wdl_draw``, ``wdl_loss``, ``san``, ``classification``,
        ``draw_character``, ``book``.
    """
    return [
        {
            "ply": m.ply,
            "wdl_win": m.wdl_win_adj,
            "wdl_draw": m.wdl_draw_adj,
            "wdl_loss": m.wdl_loss_adj,
            "san": m.san,
            "classification": (m.base_severity or "").lower(),
            "draw_character": (m.draw_character or "").lower().replace(" ", "_"),
            "book": m.ply <= data.book_ply_count,
        }
        for m in data.lc0_moves
    ]
