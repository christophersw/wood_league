"""
Title: chart_data.py — JSON-shape builders for the three analysis charts
Description:
    Each function returns a list of small dicts that the corresponding
    chart partial dumps via json_script. No HTML, no Plotly.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

import math

from games.services_v2 import GameAnalysisDataV2

_LICHESS_K = 0.00368208


def _cp_to_winpct(cp: float) -> float:
    """Lichess logistic: convert centipawn eval to Win-for-White percentage."""
    return 50.0 + 50.0 * math.tanh(_LICHESS_K * cp)


def winpct_payload(data: GameAnalysisDataV2) -> dict:
    return {
        "sf": [
            {"ply": m.ply, "winpct": _cp_to_winpct(m.cp_eval), "san": m.san}
            for m in data.sf_moves
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
