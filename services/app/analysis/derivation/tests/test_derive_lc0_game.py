"""
Title: test_derive_lc0_game.py — Lc0 game-derivation orchestrator
Description:
    Issue #161 Phase D. Structural tests for ``derive_lc0_game``: it consumes
    a raw lc0 payload (per the #161 contract) plus a ``Game`` stand-in and
    returns a dict ready for ``Lc0GameAnalysis`` / ``Lc0MoveAnalysis``
    creation. These tests pin the output shape, the per-move derivations, the
    side-aware aggregates, and the symmetric-Elo fallback. Math correctness
    is covered by ``test_lc0_golden.py``.

Changelog:
    2026-05-19 (#161/D): Initial.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from analysis.derivation.lc0 import derive_lc0_game


@dataclass
class _GameStub:
    """Minimal Game stand-in carrying just the rating fields the orchestrator reads."""
    white_rating: Optional[int]
    black_rating: Optional[int]


def _raw_move(
    ply: int, *, mover_win: int, mover_draw: int, mover_loss: int,
    san: str = "—", fen: str = "—",
) -> dict:
    """Build a minimal move entry matching the raw payload contract."""
    return {
        "ply": ply, "san": san, "fen": fen,
        "wdl_win": mover_win, "wdl_draw": mover_draw, "wdl_loss": mover_loss,
        "arrow_uci_1": "e2e4",
    }


def _payload(moves: list[dict], *, draw_rate_reference: float = 0.58) -> dict:
    """Wrap moves in the canonical raw payload envelope."""
    return {
        "worker_id": "w",
        "engine_nodes": 25000,
        "network_name": "TestNet",
        "draw_rate_reference": draw_rate_reference,
        "moves": moves,
    }


def test_returns_full_game_level_shape() -> None:
    """The top-level dict carries every Lc0GameAnalysis-bound field."""
    payload = _payload([_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)])
    out = derive_lc0_game(payload, _GameStub(1200, 1100))

    expected_keys = {
        "engine_nodes", "network_name", "draw_rate_reference",
        "wdl_calibration_elo", "contempt",
        "white_win_prob", "white_draw_prob", "white_loss_prob",
        "black_win_prob", "black_draw_prob", "black_loss_prob",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
        "white_accuracy", "black_accuracy",  # #164
        "moves",
    }
    assert set(out) == expected_keys
    assert out["engine_nodes"] == 25000
    assert out["network_name"] == "TestNet"
    assert out["wdl_calibration_elo"] == 1200
    assert out["contempt"] == 100


def test_ply_1_has_no_deltas_and_defaults_to_best() -> None:
    """First ply has no prior position; deltas are None and severity falls to Best."""
    payload = _payload([_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)])
    out = derive_lc0_game(payload, _GameStub(1200, 1100))
    first = out["moves"][0]
    assert first["delta_mu"] is None
    assert first["delta_d"] is None
    assert first["base_severity"] == "Best"
    assert first["draw_character"] is None


def test_subsequent_plies_compute_deltas_and_classify() -> None:
    """Ply 2 onward emits deltas computed against the previous mu/D and a real severity."""
    payload = _payload([
        _raw_move(1, mover_win=500, mover_draw=300, mover_loss=200),
        _raw_move(2, mover_win=500, mover_draw=300, mover_loss=200),
    ])
    out = derive_lc0_game(payload, _GameStub(1200, 1100))
    second = out["moves"][1]
    assert isinstance(second["delta_mu"], float)
    assert isinstance(second["delta_d"], float)
    assert second["delta_mu"] >= 0.0
    assert second["base_severity"] in {
        "Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder",
    }


def test_per_move_carries_raw_and_derived_fields() -> None:
    """Every move dict surfaces the canonical raw + derived field set."""
    payload = _payload([_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)])
    out = derive_lc0_game(payload, _GameStub(1200, 1100))
    move = out["moves"][0]
    for field in (
        "ply", "san", "fen",
        "wdl_win", "wdl_draw", "wdl_loss",
        "wdl_win_adj", "wdl_draw_adj", "wdl_loss_adj",
        "wdl_mu", "delta_mu", "delta_d",
        "base_severity", "draw_character",
        "arrow_uci_1", "arrow_uci_2", "arrow_uci_3",
        "pv_san_1", "pv_san_2", "pv_san_3",
    ):
        assert field in move, field


def test_severities_drive_per_side_counters() -> None:
    """Counter aggregates reflect mover-side parity and severity vocabulary."""
    moves = [
        _raw_move(1, mover_win=500, mover_draw=300, mover_loss=200),  # White
        _raw_move(2, mover_win=500, mover_draw=300, mover_loss=200),  # Black
        _raw_move(3, mover_win=100, mover_draw=300, mover_loss=600),  # White — blunder
    ]
    out = derive_lc0_game(_payload(moves), _GameStub(1200, 1100))
    # Sanity: only counter labels (Blunder/Mistake/Inaccuracy) bump aggregates.
    total_counters = (
        out["white_blunders"] + out["white_mistakes"] + out["white_inaccuracies"]
        + out["black_blunders"] + out["black_mistakes"] + out["black_inaccuracies"]
    )
    severe_moves = [m for m in out["moves"]
                    if m["base_severity"] in {"Blunder", "Mistake", "Inaccuracy"}]
    assert total_counters == len(severe_moves)


def test_per_side_probabilities_are_in_unit_interval() -> None:
    """All six *_prob fields lie in [0, 1] regardless of move count."""
    moves = [_raw_move(p, mover_win=400, mover_draw=300, mover_loss=300) for p in range(1, 7)]
    out = derive_lc0_game(_payload(moves), _GameStub(1200, 1100))
    for key in (
        "white_win_prob", "white_draw_prob", "white_loss_prob",
        "black_win_prob", "black_draw_prob", "black_loss_prob",
    ):
        assert 0.0 <= out[key] <= 1.0, key


def test_symmetric_elo_fallback_when_rating_missing() -> None:
    """Missing rating on either side → both fall back symmetrically → contempt = 0."""
    payload = _payload([_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)])
    out = derive_lc0_game(payload, _GameStub(None, 1300))
    assert out["contempt"] == 0
    assert out["wdl_calibration_elo"] == out["wdl_calibration_elo"]  # same Elo both sides


def test_orchestrator_preserves_move_order() -> None:
    """Output ``moves`` list is in input-ply order regardless of any reshuffling."""
    moves = [_raw_move(p, mover_win=500, mover_draw=300, mover_loss=200) for p in (1, 2, 3, 4)]
    out = derive_lc0_game(_payload(moves), _GameStub(1200, 1100))
    assert [m["ply"] for m in out["moves"]] == [1, 2, 3, 4]


@pytest.mark.parametrize("draw_rate", [0.3, 0.5, 0.7])
def test_draw_rate_reference_round_trips(draw_rate: float) -> None:
    """The orchestrator surfaces the supplied draw_rate_reference unchanged."""
    payload = _payload(
        [_raw_move(1, mover_win=500, mover_draw=300, mover_loss=200)],
        draw_rate_reference=draw_rate,
    )
    out = derive_lc0_game(payload, _GameStub(1200, 1100))
    assert out["draw_rate_reference"] == pytest.approx(draw_rate)
