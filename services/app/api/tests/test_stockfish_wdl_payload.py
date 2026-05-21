"""
Title: test_stockfish_wdl_payload.py — Tests for #188 Phase A app WDL serializer
Description:
    Round-trip tests verifying that StockfishCompleteSerializer accepts the new
    nullable WDL fields introduced in Phase A, enforces the per-slot all-or-nothing
    invariant, and rejects triples whose milli-unit sum falls outside [990, 1010].
    Older worker payloads without WDL fields must still validate (backwards compat).

Changelog:
    2026-05-21 (#188/A): Initial creation.
"""
import pytest
from rest_framework.exceptions import ValidationError

from api.serializers import StockfishCompleteSerializer


def _minimal_payload(**move_overrides):
    """Build a minimal valid Stockfish payload with optional move-level overrides."""
    move = {
        "ply": 1, "san": "e4", "fen": "x" * 30, "cp_eval": 30,
        "arrow_uci_1": "e7e5",
    }
    move.update(move_overrides)
    return {
        "worker_id": "w-1", "engine_depth": 20, "engine_name": "Stockfish 16",
        "moves": [move],
    }


def test_payload_validates_without_wdl_fields():
    """Backwards compat: Phase A payloads from older workers must still validate."""
    s = StockfishCompleteSerializer(data=_minimal_payload())
    assert s.is_valid(), s.errors


def test_payload_validates_with_wdl_fields():
    """A payload with full WDL triples and NPV validates and exposes the values."""
    payload = _minimal_payload(
        wdl_win=120, wdl_draw=850, wdl_loss=30,
        wdl_win_1=120, wdl_draw_1=850, wdl_loss_1=30,
    )
    payload["normalize_to_pawn_value"] = 328
    s = StockfishCompleteSerializer(data=payload)
    assert s.is_valid(), s.errors
    assert s.validated_data["normalize_to_pawn_value"] == 328
    assert s.validated_data["moves"][0]["wdl_win"] == 120


def test_payload_rejects_played_wdl_with_bad_sum():
    """SF WDL must sum to ~1000 milli when present, mirroring Lc0's validator."""
    payload = _minimal_payload(wdl_win=500, wdl_draw=400, wdl_loss=400)  # sum 1300
    s = StockfishCompleteSerializer(data=payload)
    assert not s.is_valid()
    assert "wdl_win" in s.errors["moves"][0]


def test_payload_accepts_npv_null():
    """A payload with normalize_to_pawn_value=None validates."""
    payload = _minimal_payload()
    payload["normalize_to_pawn_value"] = None
    s = StockfishCompleteSerializer(data=payload)
    assert s.is_valid(), s.errors


def test_payload_partial_wdl_triple_rejected():
    """All-or-nothing per slot: providing wdl_win without wdl_draw/loss is malformed."""
    payload = _minimal_payload(wdl_win=120)  # missing draw + loss
    s = StockfishCompleteSerializer(data=payload)
    assert not s.is_valid()
