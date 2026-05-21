"""
Title: chart_data.py — JSON-shape builders for the three analysis charts
Description:
    Each function returns a list of small dicts that the corresponding
    chart partial dumps via json_script. No HTML, no Plotly.

Changelog:
    2026-05-21 (#186): Initial.
"""
from __future__ import annotations

from analysis.derivation.accuracy import win_pct
from games.services_v2 import GameAnalysisDataV2


def winpct_payload(data: GameAnalysisDataV2) -> dict:
    """Build the Win%-chart payload for both engines on a shared 0–100 axis.

    SF Win% comes from the canonical Lichess sigmoid in
    ``analysis.derivation.accuracy.win_pct`` — the same function the accuracy
    and classification pipelines use, so the chart can never drift from the
    rest of the SF math. LC0 Win% is just ``wdl_mu * 100`` (already a
    White-frame expected score in [0, 1]).

    See GitHub issue #188 for the planned switch to SF-native WDL via
    ``UCI_ShowWDL``, which will remove the sigmoid from this code path
    entirely.
    """
    return {
        "sf": [
            {"ply": m.ply, "winpct": win_pct(m.cp_eval), "san": m.san}
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
