"""
Title: test_serializers.py — Unit tests for API request serializers
Description:
    Pure-Python tests against the DRF serializers in
    ``api.serializers`` — no DB or HTTP layer involved. Currently covers
    the regression where ``Lc0MoveSerializer`` rejected empty
    ``arrow_uci_2``/``arrow_uci_3`` strings, failing whole analysis jobs
    when a position had fewer than 3 candidate PV lines (issue #59).

Changelog:
    2026-05-13: Initial creation (issue #59)
"""
from __future__ import annotations

from django.test import SimpleTestCase

from api.serializers import Lc0MoveSerializer


def _valid_lc0_move_payload(**overrides) -> dict:
    """Build a minimal valid Lc0MoveSerializer payload.

    Args:
        overrides: Field values to merge onto the base payload.

    Returns:
        Dict suitable for ``Lc0MoveSerializer(data=...)``.
    """
    base = {
        'ply': 1,
        'san': 'e4',
        'fen': 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1',
        'wdl_win': 500,
        'wdl_draw': 400,
        'wdl_loss': 100,
        'cp_equiv': 28,
        'best_move': 'e4',
        'move_win_delta': 0.7,
        'classification': 'Best',
        'arrow_uci': 'e2e4',
        'arrow_uci_2': 'd2d4',
        'arrow_uci_3': 'g1f3',
        'arrow_score_1': 50.0,
        'arrow_score_2': 49.0,
        'arrow_score_3': 48.0,
        'pv_san_1': '["e4"]',
        'pv_san_2': '["d4"]',
        'pv_san_3': '["Nf3"]',
    }
    base.update(overrides)
    return base


class Lc0MoveSerializerArrowUciBlankTests(SimpleTestCase):
    """Regression coverage for issue #59 — blank arrow_uci_* must validate."""

    def test_blank_arrow_uci_3_is_accepted(self):
        """Empty string for arrow_uci_3 must not fail validation.

        Mirrors the production payload from job 7537 where the worker
        sent {"arrow_uci_3": ""} for a ply with only two candidate PV
        lines, and the API rejected the whole multi-move submission.
        """
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci_3=''))
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        self.assertEqual(ser.validated_data['arrow_uci_3'], '')

    def test_blank_arrow_uci_2_is_accepted(self):
        """Same allowance applies to the 2nd-best PV slot."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci_2=''))
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        self.assertEqual(ser.validated_data['arrow_uci_2'], '')

    def test_blank_primary_arrow_uci_is_accepted(self):
        """And to the primary arrow — kept consistent with the stockfish path."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci=''))
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        self.assertEqual(ser.validated_data['arrow_uci'], '')

    def test_all_three_blank_is_accepted(self):
        """Combined: a terminal position with no PV candidates."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(
            arrow_uci='', arrow_uci_2='', arrow_uci_3='',
        ))
        self.assertTrue(ser.is_valid(), msg=ser.errors)

    def test_missing_arrow_uci_keys_still_default_to_blank(self):
        """Field is required=False; missing keys default to ''."""
        payload = _valid_lc0_move_payload()
        for key in ('arrow_uci', 'arrow_uci_2', 'arrow_uci_3'):
            payload.pop(key, None)
        ser = Lc0MoveSerializer(data=payload)
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        for key in ('arrow_uci', 'arrow_uci_2', 'arrow_uci_3'):
            self.assertEqual(ser.validated_data[key], '')

    def test_oversize_arrow_uci_still_rejected(self):
        """allow_blank=True must not relax the max_length=8 guard."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci_3='abcdefghij'))
        self.assertFalse(ser.is_valid())
        self.assertIn('arrow_uci_3', ser.errors)
