"""
Title: chart_data.py — JSON-shape builders for the three analysis charts
Description:
    Each function returns a list of small dicts that the corresponding
    chart partial dumps via json_script. No HTML, no Plotly.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

from games.services_v2 import GameAnalysisDataV2


def winpct_payload(data: GameAnalysisDataV2) -> dict:
    """Build the Win%-chart payload for both engines on a shared 0–100 axis.

    Both engines read Win% from their stored White-frame WDL (#188): SF from
    ``wdl_*_adj`` (frame-mirror identity), LC0 from ``wdl_mu``. No Lichess
    sigmoid — SF and LC0 now speak the same units. SF moves without a WDL
    triple (the missing-WDL fallback) drop from the chart rather than being
    reconstructed from cp, mirroring how LC0 skips ``wdl_mu is None`` rows.
    """
    return {
        "sf": [
            {
                "ply": m.ply,
                "winpct": ((m.wdl_win_adj + m.wdl_draw_adj / 2) / 1000.0) * 100.0,
                "san": m.san,
            }
            for m in data.sf_moves
            if m.wdl_win_adj is not None and m.wdl_draw_adj is not None
        ],
        "lc0": [
            {"ply": m.ply, "winpct": (m.wdl_mu or 0.0) * 100.0, "san": m.san}
            for m in data.lc0_moves
            if m.wdl_mu is not None
        ],
    }


def sf_cp_payload(data: GameAnalysisDataV2) -> list[dict]:
    return [
        {
            "ply": m.ply,
            "cp_eval": m.cp_eval,
            "mate_in": m.mate_in,
            "classification": (m.classification or "").lower(),
            "san": m.san,
        }
        for m in data.sf_moves
    ]


def lc0_wdl_payload(data: GameAnalysisDataV2) -> list[dict]:
    return [
        {
            "ply": m.ply,
            "wdl_win": m.wdl_win_adj,
            "wdl_draw": m.wdl_draw_adj,
            "wdl_loss": m.wdl_loss_adj,
            "san": m.san,
        }
        for m in data.lc0_moves
    ]
