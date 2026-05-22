"""
Title: test_stockfish_wdl_mu.py — SF WDL_mu derivation math (#188 Phase C)
Description:
    Unit and integration tests for the WDL_mu math switch in the Stockfish
    derivation pipeline. Phase C scope: WDL drives the *accuracy* Win% only;
    the classifier's second-best gap stays cp-based via arrow scores. Covers:
      - Frame mirror helpers (_sf_wdl_mover_to_white, _sf_wdl_mu_white)
      - _derive_one_move WDL path and fallback path
      - derive_sf_game walk: mu threading, NPV pass-through (metadata)
      - Black-mover frame correctness
      - Mate saturation on WDL path
      - 1-ply game edge case

Changelog:
    2026-05-21 (#188/C): Initial.
    2026-05-21 (#188/C): Drop WDL-gap tests — classifier gap reverted to the
        cp-based arrow-score path; native-cp gap deferred to SF-candidate-cp.
"""
from __future__ import annotations

import pytest

from analysis.derivation.stockfish import (
    _sf_wdl_mover_to_white,
    _sf_wdl_mu_white,
)


# ── Task C1: WDL helpers ─────────────────────────────────────────────────


@pytest.mark.parametrize("triple,expected", [
    ((1000, 0, 0), 1.0),
    ((0, 1000, 0), 0.5),
    ((0, 0, 1000), 0.0),
    ((100, 800, 100), 0.5),
    ((200, 700, 100), 0.55),
])
def test_sf_wdl_mu_white(triple, expected):
    """_sf_wdl_mu_white computes (W + D/2)/1000 in White's frame."""
    assert _sf_wdl_mu_white(*triple) == pytest.approx(expected, abs=1e-9)


def test_sf_wdl_mover_to_white_white_mover_identity():
    """White-mover triple passes through unchanged."""
    assert _sf_wdl_mover_to_white(120, 850, 30, mover_is_white=True) == (120, 850, 30)


def test_sf_wdl_mover_to_white_black_mover_swaps_win_loss():
    """Black-mover triple swaps W↔L; draw is symmetric."""
    assert _sf_wdl_mover_to_white(120, 850, 30, mover_is_white=False) == (30, 850, 120)


# ── Task C2: _derive_one_move ────────────────────────────────────────────

from analysis.derivation.stockfish import _derive_one_move  # noqa: E402


def _move(**overrides):
    """Build a minimal raw SF move entry with WDL triples populated.

    Args:
        **overrides: Field overrides applied to the base move dict.

    Returns:
        dict: A raw move dict matching the #161/#188 SF contract.
    """
    base = {
        "ply": 1, "san": "e4", "fen": "x" * 30,
        "cp_eval": 30, "mate_in": None,
        "arrow_uci_1": "e7e5", "arrow_uci_2": "c7c5", "arrow_uci_3": "",
        "arrow_cp_1": 30, "arrow_cp_2": 12, "arrow_cp_3": None,
        "pv_san_1": '["e5"]', "pv_san_2": '["c5"]', "pv_san_3": None,
        "wdl_win": 200, "wdl_draw": 700, "wdl_loss": 100,
        "wdl_win_1": 220, "wdl_draw_1": 700, "wdl_loss_1": 80,
        "wdl_win_2": 180, "wdl_draw_2": 720, "wdl_loss_2": 100,
        "wdl_win_3": None, "wdl_draw_3": None, "wdl_loss_3": None,
    }
    base.update(overrides)
    return base


def test_derive_one_move_uses_wdl_mu_when_present():
    """WDL path: mover-frame triple → White-frame adj + wdl_mu."""
    out = _derive_one_move(_move(), before_white_mu=0.5)
    # Ply 1 = White mover; mover-frame = White-frame (identity).
    # wdl_win_adj=200, wdl_draw_adj=700, wdl_loss_adj=100
    assert (out["wdl_win_adj"], out["wdl_draw_adj"], out["wdl_loss_adj"]) == (200, 700, 100)
    # wdl_mu = (200 + 700/2) / 1000 = 0.55
    assert out["wdl_mu"] == pytest.approx(0.55)
    # move_win_delta: before=50.0 (mu=0.5→50%), after=55.0; delta= -(after-before) = -(5) = -5
    # Actually: win_pct_before_mover - win_pct_after_mover = 50.0 - 55.0 = -5
    assert out["move_win_delta"] == pytest.approx(50.0 - 55.0)


def test_derive_one_move_black_mover_swaps_frame():
    """Black-mover: mover-frame (100,700,200) → White-frame (200,700,100), mu=0.55."""
    move = _move(ply=2, wdl_win=100, wdl_draw=700, wdl_loss=200)
    out = _derive_one_move(move, before_white_mu=0.5)
    assert (out["wdl_win_adj"], out["wdl_draw_adj"], out["wdl_loss_adj"]) == (200, 700, 100)
    assert out["wdl_mu"] == pytest.approx(0.55)


def test_derive_one_move_falls_back_to_sigmoid_when_wdl_missing():
    """Fallback path: no WDL → _adj stays null, wdl_mu is None, still classifies."""
    move = _move()
    for k in ("wdl_win", "wdl_draw", "wdl_loss"):
        move[k] = None
    out = _derive_one_move(move, before_white_mu=0.5)
    assert out["wdl_win_adj"] is None
    assert out["wdl_draw_adj"] is None
    assert out["wdl_loss_adj"] is None
    assert out["wdl_mu"] is None
    assert out["classification"] is not None
    assert out["cpl"] is not None


def test_derive_one_move_mate_saturates():
    """mate_in=3 → wdl_mu near 1.0 (saturated WDL triple)."""
    move = _move(cp_eval=0, mate_in=3, wdl_win=999, wdl_draw=1, wdl_loss=0)
    out = _derive_one_move(move, before_white_mu=0.5)
    assert out["wdl_mu"] > 0.99


def test_derive_one_move_cpl_is_cp_based_not_mu():
    """CPL must remain cp-based on the WDL path — no mu conversion."""
    # White at 0cp before, move plays to cp_eval=-200 → mover CPL=200.
    move = _move(ply=1, cp_eval=-200, wdl_win=100, wdl_draw=600, wdl_loss=300)
    out = _derive_one_move(move, before_white=0, before_white_mu=0.5)
    assert out["cpl"] == 200


def test_derive_one_move_wdl_raw_passthrough_unchanged():
    """Raw WDL triples survive the derivation verbatim."""
    out = _derive_one_move(_move(), before_white_mu=0.5)
    assert (out["wdl_win"], out["wdl_draw"], out["wdl_loss"]) == (200, 700, 100)
    assert (out["wdl_win_1"], out["wdl_draw_1"], out["wdl_loss_1"]) == (220, 700, 80)


# ── Task C3: derive_sf_game walk + NPV ───────────────────────────────────

from analysis.derivation.stockfish import derive_sf_game  # noqa: E402


def test_derive_sf_game_walks_mu_through():
    """Mu propagates: ply 2 sees ply 1's White-frame mu as its before_white_mu."""
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [
            _move(ply=1, wdl_win=200, wdl_draw=700, wdl_loss=100),  # mu_w=0.55
            _move(ply=2, wdl_win=300, wdl_draw=600, wdl_loss=100),  # Black mover
        ],
    }
    derived = derive_sf_game(payload, game=None)
    # Ply 1: White mover, (200,700,100) → mu_white=0.55
    assert derived["moves"][0]["wdl_mu"] == pytest.approx(0.55)
    # Ply 2: Black mover, mover-frame (300,600,100) → White-frame (100,600,300)
    # mu_white = (100 + 600/2)/1000 = (100+300)/1000 = 0.4
    assert derived["moves"][1]["wdl_mu"] == pytest.approx(0.4)


def test_derive_sf_game_top_level_npv_passed_through():
    """normalize_to_pawn_value surfaces at the top level of derived output."""
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [_move()],
    }
    assert derive_sf_game(payload, game=None)["normalize_to_pawn_value"] == 328


def test_derive_sf_game_fallback_path_still_produces_accuracy():
    """Fallback (no WDL): per-side accuracy is still computed via cp sigmoid."""
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "moves": [
            {"ply": 1, "san": "e4", "fen": "x" * 30, "cp_eval": 30, "mate_in": None,
             "arrow_uci_1": "e2e4", "arrow_cp_1": 30, "arrow_cp_2": 12},
            {"ply": 2, "san": "e5", "fen": "x" * 30, "cp_eval": -10, "mate_in": None,
             "arrow_uci_1": "e7e5"},
        ],
    }
    derived = derive_sf_game(payload, game=None)
    assert derived["white_accuracy"] is not None
    assert derived["black_accuracy"] is not None
    assert derived["moves"][0]["wdl_win_adj"] is None


def test_derive_sf_game_one_ply_game():
    """A 1-ply game doesn't crash; black_accuracy is None (no Black moves)."""
    payload = {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "normalize_to_pawn_value": 328,
        "moves": [_move(ply=1)],
    }
    derived = derive_sf_game(payload, game=None)
    assert derived["white_accuracy"] is not None
    assert derived["moves"][0]["wdl_mu"] == pytest.approx(0.55)
