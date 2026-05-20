"""
Title: test_serializers_raw_payload.py — #161 Phase G serializer contracts
Description:
    Issue #161 Phase G. After this phase the worker emits *raw observables
    only* and the app derives every classification / calibration / aggregate
    field via ``analysis.derivation``. These tests pin:

    * ``Lc0CompleteSerializer`` accepts the new raw payload and rejects
      pre-#161 shapes (no ``wdl_*_adj``, ``base_severity``, etc.).
    * ``StockfishCompleteSerializer`` accepts the new SF payload and rejects
      pre-#161 shapes (no ``cpl``, ``classification``, ``white_accuracy``,
      etc.).
    * Both reject obvious raw-WDL invariants (sum > 1000, missing required
      fields).

    The end-to-end "POST → derive → persist" check lives in
    ``test_complete_endpoint_derives.py``.

Changelog:
    2026-05-20 (#161/G): Initial.
"""
from __future__ import annotations

from api.serializers import (
    Lc0CompleteSerializer,
    StockfishCompleteSerializer,
)


# ── Lc0 ──────────────────────────────────────────────────────────────────


_LC0_RAW_MOVE = {
    "ply": 1, "san": "e4", "fen": "—",
    "wdl_win": 500, "wdl_draw": 300, "wdl_loss": 200,
    "arrow_uci_1": "e2e4", "arrow_uci_2": "d2d4", "arrow_uci_3": None,
    "wdl_win_1": 510, "wdl_draw_1": 290, "wdl_loss_1": 200,
    "wdl_win_2": 480, "wdl_draw_2": 310, "wdl_loss_2": 210,
    "wdl_win_3": None, "wdl_draw_3": None, "wdl_loss_3": None,
    "pv_san_1": "[\"e4\", \"e5\"]", "pv_san_2": None, "pv_san_3": None,
}


def _lc0_payload(**overrides):
    body = {
        "worker_id": "w-1",
        "engine_nodes": 25000,
        "network_name": "BT4-1740",
        "draw_rate_reference": 0.58,
        "moves": [_LC0_RAW_MOVE],
    }
    body.update(overrides)
    return body


def test_lc0_raw_payload_validates_clean():
    """A canonical raw payload passes validation."""
    ser = Lc0CompleteSerializer(data=_lc0_payload())
    assert ser.is_valid(), ser.errors


def test_lc0_rejects_pre_161_derived_fields():
    """Pre-#161 worker output that includes derived fields is refused."""
    legacy_move = {
        **_LC0_RAW_MOVE,
        "wdl_win_adj": 500, "wdl_draw_adj": 300, "wdl_loss_adj": 200,
        "base_severity": "Best", "delta_mu": 0.0, "delta_d": 0.0,
        "cp_equiv": 12, "best_move": "e2e4",
    }
    payload = _lc0_payload(moves=[legacy_move])
    payload["wdl_calibration_elo"] = 1200
    payload["contempt"] = 100
    payload["white_win_prob"] = 0.5
    ser = Lc0CompleteSerializer(data=payload)
    assert not ser.is_valid()


def test_lc0_rejects_missing_required_fields():
    """A move without raw WDL is refused."""
    bad = {k: v for k, v in _LC0_RAW_MOVE.items() if k != "wdl_win"}
    ser = Lc0CompleteSerializer(data=_lc0_payload(moves=[bad]))
    assert not ser.is_valid()
    assert "moves" in ser.errors


def test_lc0_rejects_wdl_sum_out_of_range():
    """A raw WDL triple summing to >1000 milli-units is refused."""
    bad = {**_LC0_RAW_MOVE, "wdl_win": 800, "wdl_draw": 800, "wdl_loss": 800}
    ser = Lc0CompleteSerializer(data=_lc0_payload(moves=[bad]))
    assert not ser.is_valid()


# ── Stockfish ────────────────────────────────────────────────────────────


_SF_RAW_MOVE = {
    "ply": 1, "san": "e4", "fen": "—",
    "cp_eval": 30, "mate_in": None,
    "arrow_uci_1": "e2e4", "arrow_uci_2": "d2d4", "arrow_uci_3": None,
    "arrow_score_1": 55.0, "arrow_score_2": 53.0, "arrow_score_3": None,
    "pv_san_1": "[\"e4\", \"e5\"]", "pv_san_2": None, "pv_san_3": None,
}


def _sf_payload(**overrides):
    body = {
        "worker_id": "w-1",
        "engine_depth": 20,
        "engine_name": "Stockfish 16",
        "moves": [_SF_RAW_MOVE],
    }
    body.update(overrides)
    return body


def test_sf_raw_payload_validates_clean():
    """A canonical raw SF payload passes validation."""
    ser = StockfishCompleteSerializer(data=_sf_payload())
    assert ser.is_valid(), ser.errors


def test_sf_rejects_pre_161_derived_game_fields():
    """A SF payload that carries pre-#161 derived aggregates is refused."""
    payload = _sf_payload()
    payload["white_accuracy"] = 95.0
    payload["white_blunders"] = 1
    ser = StockfishCompleteSerializer(data=payload)
    assert not ser.is_valid()


def test_sf_rejects_pre_161_derived_move_fields():
    """A SF move carrying pre-#161 derived fields (cpl, classification) is refused."""
    legacy_move = {**_SF_RAW_MOVE, "cpl": 5, "classification": "Best", "best_move": "e2e4"}
    ser = StockfishCompleteSerializer(data=_sf_payload(moves=[legacy_move]))
    assert not ser.is_valid()


def test_sf_mate_in_is_nullable_signed_integer():
    """``mate_in`` may be null, positive (White mates), or negative (Black mates)."""
    for value in (None, 3, -5):
        move = {**_SF_RAW_MOVE, "mate_in": value}
        ser = StockfishCompleteSerializer(data=_sf_payload(moves=[move]))
        assert ser.is_valid(), (value, ser.errors)


def test_sf_rejects_missing_cp_eval():
    """A SF move without ``cp_eval`` is refused (raw observable required)."""
    bad = {k: v for k, v in _SF_RAW_MOVE.items() if k != "cp_eval"}
    ser = StockfishCompleteSerializer(data=_sf_payload(moves=[bad]))
    assert not ser.is_valid()
