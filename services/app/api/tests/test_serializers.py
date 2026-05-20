"""
Title: test_serializers.py — Unit tests for API request serializers
Description:
    Pure-Python tests against the DRF serializers in
    ``api.serializers`` — no DB or HTTP layer involved. Currently covers
    the regression where ``Lc0MoveSerializer`` rejected empty
    ``arrow_uci_2``/``arrow_uci_3`` strings, failing whole analysis jobs
    when a position had fewer than 3 candidate PV lines (issue #59).
    Also covers HeartbeatSerializer backward-compatibility and new batch
    progress fields (issue #128).

Changelog:
    2026-05-13: Initial creation (issue #59)
    2026-05-17: Add HeartbeatSerializer batch-fields tests (issue #128)
    2026-05-17: Add JobSerializer lc0 null-nodes resolution tests (issue #141)
"""
from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from api.serializers import JobSerializer, Lc0MoveSerializer


def _job_stub(*, engine: str, nodes, depth: int = 20) -> SimpleNamespace:
    """Build a lightweight stand-in for an AnalysisJob row.

    JobSerializer is a plain (non-ModelSerializer) Serializer that only
    reads attributes, so a SimpleNamespace avoids any DB dependency.

    Args:
        engine: 'lc0' or 'stockfish'.
        nodes: the job's stored nodes value (int or None).
        depth: the job's stored Stockfish depth (default 20).

    Returns:
        SimpleNamespace shaped like a claimed AnalysisJob.
    """
    return SimpleNamespace(
        id=1,
        game=SimpleNamespace(id='g-1', pgn='*'),
        engine=engine,
        depth=depth,
        nodes=nodes,
        worker_id='w-1',
        claimed_by_key_prefix='abcd1234',
    )


@override_settings(LC0_NODES=25000)
class JobSerializerNodesResolutionTests(SimpleTestCase):
    """Issue #141 — the worker must never receive null nodes for lc0.

    requeue_all_analysis created lc0 jobs with nodes=NULL; the server
    forwarded {nodes: null, depth: 20} and the worker ran ~20 nodes.
    """

    def test_lc0_null_nodes_resolves_to_setting(self):
        """An lc0 job with nodes=None serializes as settings.LC0_NODES."""
        data = JobSerializer(_job_stub(engine='lc0', nodes=None)).data
        self.assertEqual(data['nodes'], 25000)

    def test_lc0_explicit_nodes_is_respected(self):
        """An lc0 job with an explicit nodes value is left untouched."""
        data = JobSerializer(_job_stub(engine='lc0', nodes=12345)).data
        self.assertEqual(data['nodes'], 12345)

    def test_stockfish_nodes_stays_null(self):
        """Stockfish ignores nodes (uses depth); null must stay null."""
        data = JobSerializer(_job_stub(engine='stockfish', nodes=None)).data
        self.assertIsNone(data['nodes'])
        self.assertEqual(data['depth'], 20)


def _valid_lc0_move_payload(**overrides) -> dict:
    """Build a minimal valid Lc0MoveSerializer payload.

    Args:
        overrides: Field values to merge onto the base payload.

    Returns:
        Dict suitable for ``Lc0MoveSerializer(data=...)``.
    """
    # #161 G: payload is *raw* only. Rescaled WDL / severity / cp_equiv etc.
    # are derived app-side; they no longer belong in the worker's payload.
    base = {
        'ply': 1,
        'san': 'e4',
        'fen': 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1',
        'wdl_win': 500,
        'wdl_draw': 400,
        'wdl_loss': 100,
        'arrow_uci_1': 'e2e4',
        'arrow_uci_2': 'd2d4',
        'arrow_uci_3': 'g1f3',
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
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci_1=''))
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        self.assertEqual(ser.validated_data['arrow_uci_1'], '')

    def test_all_three_blank_is_accepted(self):
        """Combined: a terminal position with no PV candidates."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(
            arrow_uci_1='', arrow_uci_2='', arrow_uci_3='',
        ))
        self.assertTrue(ser.is_valid(), msg=ser.errors)

    def test_missing_secondary_arrow_uci_keys_default_to_null(self):
        """#161 G: _2/_3 are optional+nullable; _1 is required (raw best-line UCI)."""
        payload = _valid_lc0_move_payload()
        for key in ('arrow_uci_2', 'arrow_uci_3'):
            payload.pop(key, None)
        ser = Lc0MoveSerializer(data=payload)
        self.assertTrue(ser.is_valid(), msg=ser.errors)
        for key in ('arrow_uci_2', 'arrow_uci_3'):
            self.assertIsNone(ser.validated_data[key])

    def test_missing_primary_arrow_uci_is_rejected(self):
        """#161 G: arrow_uci_1 carries the engine's top candidate; required."""
        payload = _valid_lc0_move_payload()
        payload.pop('arrow_uci_1')
        ser = Lc0MoveSerializer(data=payload)
        self.assertFalse(ser.is_valid())
        self.assertIn('arrow_uci_1', ser.errors)

    def test_oversize_arrow_uci_still_rejected(self):
        """allow_blank=True must not relax the max_length=8 guard."""
        ser = Lc0MoveSerializer(data=_valid_lc0_move_payload(arrow_uci_3='abcdefghij'))
        self.assertFalse(ser.is_valid())
        self.assertIn('arrow_uci_3', ser.errors)


def test_heartbeat_serializer_accepts_legacy_payload_without_batch_fields():
    """HeartbeatSerializer defaults batch fields when omitted (legacy workers).

    Legacy workers send only worker_id/engine/status_message. The serializer
    must accept the payload and produce None/0/None defaults for the three new
    batch-progress fields so existing workers keep working without changes.
    """
    from api.serializers import HeartbeatSerializer

    ser = HeartbeatSerializer(data={
        "worker_id": "w1", "engine": "lc0", "status_message": "processed=3",
    })
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["batch_total"] is None
    assert ser.validated_data["batch_processed"] == 0
    assert ser.validated_data["session_started_at"] is None


def test_heartbeat_serializer_accepts_batch_fields():
    """HeartbeatSerializer accepts and validates all three new batch-progress fields.

    New workers send batch_total, batch_processed, and session_started_at.
    The serializer must pass them through to validated_data unchanged.
    """
    from api.serializers import HeartbeatSerializer

    ser = HeartbeatSerializer(data={
        "worker_id": "w1", "engine": "lc0", "status_message": "processed=3",
        "batch_total": 6, "batch_processed": 3,
        "session_started_at": "2026-05-17T10:00:00Z",
    })
    assert ser.is_valid(), ser.errors
    assert ser.validated_data["batch_total"] == 6
    assert ser.validated_data["batch_processed"] == 3
    assert ser.validated_data["session_started_at"] is not None
