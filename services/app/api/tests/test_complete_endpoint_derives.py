"""
Title: test_complete_endpoint_derives.py — POST /complete persists derived fields
Description:
    Issue #161 Phase G. End-to-end check that the new raw payload flows from
    ``POST /api/v1/jobs/<id>/complete/`` through ``derivation.{lc0,stockfish}``
    and into the database, with both raw and derived columns populated.

Changelog:
    2026-05-20 (#161/G): Initial.
"""
from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from analysis.calibration_hash import current_lc0_settings_hash
from analysis.models import (
    AnalysisJob,
    GameAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    MoveAnalysis,
    NetworkCalibration,
)
from api.models import WorkerAPIKey
from games.models import Game


def _lc0_raw_move(ply: int) -> dict:
    return {
        "ply": ply, "san": "e4" if ply == 1 else "e5", "fen": "—",
        "wdl_win": 500, "wdl_draw": 300, "wdl_loss": 200,
        "arrow_uci_1": "e2e4", "arrow_uci_2": None, "arrow_uci_3": None,
        "wdl_win_1": 510, "wdl_draw_1": 290, "wdl_loss_1": 200,
        "wdl_win_2": None, "wdl_draw_2": None, "wdl_loss_2": None,
        "wdl_win_3": None, "wdl_draw_3": None, "wdl_loss_3": None,
        "pv_san_1": None, "pv_san_2": None, "pv_san_3": None,
    }


def _sf_raw_move(ply: int, cp_eval: int = 30) -> dict:
    return {
        "ply": ply, "san": "e4" if ply == 1 else "e5", "fen": "—",
        "cp_eval": cp_eval, "mate_in": None,
        "arrow_uci_1": "e2e4", "arrow_uci_2": None, "arrow_uci_3": None,
        "arrow_cp_1": 30, "arrow_cp_2": None, "arrow_cp_3": None,
        "pv_san_1": None, "pv_san_2": None, "pv_san_3": None,
    }


class _BaseCompleteCase(TestCase):
    """Auth + job setup shared by both engine endpoint tests."""

    engine = "stockfish"

    def setUp(self):
        self.client = APIClient()
        user = User.objects.create_user(email=f"g-{uuid.uuid4().hex[:4]}@t.local", password="p")
        _, raw_key = WorkerAPIKey.objects.create_key(
            name="worker", worker_name="w", created_by=user,
        )
        self.client.credentials(HTTP_X_API_KEY=raw_key)
        self.game = Game.objects.create(
            id=f"phase-g-{uuid.uuid4().hex[:8]}",
            played_at=timezone.now(),
            time_control="600",
            pgn="1. e4 e5 *",
            white_rating=1200,
            black_rating=1100,
        )
        self.job = AnalysisJob.objects.create(
            game=self.game,
            engine=self.engine,
            status=AnalysisJob.STATUS_RUNNING,
            worker_id="w",
            claimed_by_key_prefix=self.client.credentials.__self__._credentials.get(
                "HTTP_X_API_KEY", ""
            )[:8],
        )


class Lc0CompleteEndpointTests(_BaseCompleteCase):
    """POST /complete (lc0) — raw payload → derived persistence."""

    engine = "lc0"

    def setUp(self):
        super().setUp()
        # A NetworkCalibration row is not required for the complete path —
        # but having one mirrors steady-state, since checkout would have
        # consulted it. Phase G doesn't read it here.
        NetworkCalibration.objects.create(
            network_name="BT4-1740",
            settings_hash=current_lc0_settings_hash(),
            draw_rate_reference=0.58,
            sample_size=4321, sem=0.0049,
            sampler_version="v1", submitted_by_worker_id="w-prev",
        )

    def _post(self, body):
        return self.client.post(
            f"/api/v1/jobs/{self.job.id}/complete/", body, format="json",
        )

    def _raw_body(self):
        return {
            "engine": "lc0",
            "worker_id": "w",
            "engine_nodes": 25000,
            "network_name": "BT4-1740",
            "draw_rate_reference": 0.58,
            "moves": [_lc0_raw_move(1), _lc0_raw_move(2)],
        }

    def test_post_raw_payload_creates_derived_rows(self):
        """Posting a raw payload produces an Lc0GameAnalysis + per-move rows."""
        response = self._post(self._raw_body())
        self.assertEqual(response.status_code, 200, response.content)
        lga = Lc0GameAnalysis.objects.get(game=self.game)
        self.assertEqual(lga.network_name, "BT4-1740")
        self.assertEqual(lga.engine_nodes, 25000)
        # Derived game-level fields populated.
        self.assertEqual(lga.wdl_calibration_elo, 1200)
        self.assertEqual(lga.contempt, 100)
        # Per-move rows materialised.
        moves = list(Lc0MoveAnalysis.objects.filter(analysis=lga).order_by("ply"))
        self.assertEqual([m.ply for m in moves], [1, 2])
        first = moves[0]
        # Raw fields preserved.
        self.assertEqual(first.wdl_win, 500)
        self.assertEqual(first.wdl_win_1, 510)
        self.assertEqual(first.arrow_uci_1, "e2e4")
        # Derived fields populated.
        self.assertIsNotNone(first.wdl_win_adj)
        self.assertIsNotNone(first.wdl_mu)
        # Ply 1 has no "before" position → delta_*=None, severity=Best.
        self.assertIsNone(first.delta_mu)
        self.assertEqual(first.base_severity, "Best")

    def test_post_rejects_legacy_payload_shape(self):
        """A pre-#161 worker payload (with derived fields) returns 400."""
        legacy_body = self._raw_body()
        legacy_body["wdl_calibration_elo"] = 1200
        legacy_body["white_win_prob"] = 0.5
        legacy_body["moves"][0]["base_severity"] = "Best"
        response = self._post(legacy_body)
        self.assertEqual(response.status_code, 400, response.content)


class StockfishCompleteEndpointTests(_BaseCompleteCase):
    """POST /complete (stockfish) — raw payload → derived persistence."""

    engine = "stockfish"

    def _post(self, body):
        return self.client.post(
            f"/api/v1/jobs/{self.job.id}/complete/", body, format="json",
        )

    def _raw_body(self):
        return {
            "engine": "stockfish",
            "worker_id": "w",
            "engine_depth": 20,
            "engine_name": "Stockfish 16",
            "moves": [_sf_raw_move(1, cp_eval=30), _sf_raw_move(2, cp_eval=-10)],
        }

    def test_post_raw_payload_creates_derived_rows(self):
        """Posting a raw SF payload produces GameAnalysis + per-move rows."""
        response = self._post(self._raw_body())
        self.assertEqual(response.status_code, 200, response.content)
        ga = GameAnalysis.objects.get(game=self.game)
        self.assertEqual(ga.engine_depth, 20)
        # Derived game-level aggregates set.
        self.assertIsNotNone(ga.white_accuracy)
        self.assertIsNotNone(ga.white_acpl)
        # Per-move rows materialised.
        moves = list(MoveAnalysis.objects.filter(analysis=ga).order_by("ply"))
        self.assertEqual([m.ply for m in moves], [1, 2])
        first = moves[0]
        # Raw fields preserved.
        self.assertEqual(first.cp_eval, 30)
        self.assertEqual(first.arrow_uci_1, "e2e4")
        # Derived fields populated.
        self.assertIsNotNone(first.cpl)
        self.assertIsNotNone(first.classification)

    def test_post_rejects_legacy_payload_shape(self):
        """A pre-#161 SF payload (with derived aggregates) returns 400."""
        legacy_body = self._raw_body()
        legacy_body["white_accuracy"] = 95.0
        response = self._post(legacy_body)
        self.assertEqual(response.status_code, 400, response.content)
