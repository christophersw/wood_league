"""
Title: test_checkout_needs_calibration.py — Phase B 409 response shape
Description:
    Issue #161 Phase B. When an lc0 worker checks out against an uncalibrated
    network, the API must respond with HTTP 409 and a body the worker can
    drop straight into its sampler: ``error="NEEDS_CALIBRATION"``,
    ``network_name``, ``settings_hash``, ``sampler_settings`` dict,
    ``sampler_version`` tag.

Changelog:
    2026-05-19 (#161/B): Initial.
"""
from __future__ import annotations

import uuid

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from analysis.calibration_hash import current_lc0_settings_hash
from analysis.models import AnalysisJob, NetworkCalibration
from api.models import WorkerAPIKey
from games.models import Game


def _seed_lc0_job() -> AnalysisJob:
    """Create a pending lc0 AnalysisJob for use by the tests below."""
    game = Game.objects.create(
        id=f"co-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )
    return AnalysisJob.objects.create(
        game=game, engine="lc0", status=AnalysisJob.STATUS_PENDING,
    )


class CheckoutNeedsCalibrationTests(TestCase):
    """Behaviour of POST /api/v1/jobs/checkout/ around NetworkCalibration."""

    def setUp(self):
        """Create an authenticated APIClient."""
        self.client = APIClient()
        user = User.objects.create_user(email="nc-co@test.local", password="pass")
        _, raw = WorkerAPIKey.objects.create_key(
            name="worker", worker_name="worker", created_by=user,
        )
        self.client.credentials(HTTP_X_API_KEY=raw)

    def test_uncalibrated_lc0_checkout_returns_409_needs_calibration(self):
        """The 409 body carries every field the worker needs to run the sampler."""
        _seed_lc0_job()
        response = self.client.post(
            "/api/v1/jobs/checkout/",
            {
                "engine": "lc0", "batch_size": 1, "worker_id": "w-1",
                "network_name": "UncalibNet",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.content)
        body = response.json()
        self.assertEqual(body["error"], "NEEDS_CALIBRATION")
        self.assertEqual(body["network_name"], "UncalibNet")
        self.assertEqual(body["settings_hash"], current_lc0_settings_hash())
        self.assertIn("sampler_settings", body)
        self.assertEqual(
            set(body["sampler_settings"]),
            {"sem_target", "nodes", "max_positions", "sampler_version"},
        )
        self.assertEqual(
            body["sampler_version"],
            body["sampler_settings"]["sampler_version"],
        )

    def test_calibrated_lc0_checkout_returns_200_with_draw_rate_reference(self):
        """Once a calibration row exists, the job comes back with draw_rate_reference set."""
        _seed_lc0_job()
        NetworkCalibration.objects.create(
            network_name="CalibNet",
            settings_hash=current_lc0_settings_hash(),
            draw_rate_reference=0.612,
            sample_size=4321,
            sem=0.0049,
            sampler_version="v1",
            submitted_by_worker_id="w-prev",
        )
        response = self.client.post(
            "/api/v1/jobs/checkout/",
            {
                "engine": "lc0", "batch_size": 1, "worker_id": "w-1",
                "network_name": "CalibNet",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        jobs = response.json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertAlmostEqual(jobs[0]["draw_rate_reference"], 0.612)
