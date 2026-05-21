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

# Lichess Win% logistic coefficient. Pinned constant from the Lichess engine
# scoring model — see ``wood_league.wiki/analysis-math.md`` ("Win%" section)
# and the upstream reference at
# https://github.com/lichess-org/scalachess/blob/master/core/src/main/scala/eval.scala
# This is the SAME coefficient used by ``services/app/analysis/derivation/accuracy.py``;
# both must stay in lockstep with analysis-math.md to avoid SF/LC0 Win% drift.
_LICHESS_K = 0.00368208


def _cp_to_winpct(cp: float) -> float:
    """Convert a Stockfish centipawn evaluation to a Win-for-White percentage.

    Uses the Lichess empirical sigmoid documented in
    ``wood_league.wiki/analysis-math.md`` ("Win%" section)::

        Win% = 100 / (1 + exp(-_LICHESS_K * cp))
             = 50 + 50 * tanh(_LICHESS_K * cp / 2 * 2)
             = 50 + 50 * tanh(_LICHESS_K * cp)         # algebraic identity

    The tanh form is numerically stable for large |cp|.

    Params:
        cp (float): Raw white-frame Stockfish centipawn score. Mate scores
            (|cp| >= 9000) should be clamped by the caller before passing in.

    Returns:
        float: Win-for-White percentage in [0, 100].
    """
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
