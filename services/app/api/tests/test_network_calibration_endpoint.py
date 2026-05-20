"""
Title: test_network_calibration_endpoint.py — POST /api/v1/network_calibrations/
Description:
    Phase A of issue #161. Workers POST a completed lc0 draw-rate measurement
    here. The endpoint is idempotent on (network_name, settings_hash): the
    first writer creates the row and returns 201; concurrent re-submissions
    return 200 with the existing row untouched. Inputs are validated against
    the same probability bounds the sampler enforces.

Changelog:
    2026-05-19 (#161/A): Initial failing tests for the calibrations endpoint.
"""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from analysis.models import NetworkCalibration
from api.models import WorkerAPIKey


URL = "/api/v1/network_calibrations/"


def _valid_body(**overrides):
    """Build a representative valid payload, then merge overrides."""
    body = {
        "network_name": "BT4-1740",
        "settings_hash": "c" * 64,
        "draw_rate_reference": 0.58,
        "sample_size": 4321,
        "sem": 0.0049,
        "sampler_version": "v1",
        "worker_id": "w-test",
    }
    body.update(overrides)
    return body


class NetworkCalibrationEndpointTests(TestCase):
    """Tests for POST /api/v1/network_calibrations/."""

    def setUp(self):
        """Create an authenticated APIClient and reset query state."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="nc-test@test.local", password="pass"
        )
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name="worker", worker_name="worker", created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

    def test_post_creates_row_returns_201(self):
        """First submission persists a NetworkCalibration row, returns 201."""
        body = _valid_body()
        response = self.client.post(URL, body, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        row = NetworkCalibration.objects.get(
            network_name=body["network_name"],
            settings_hash=body["settings_hash"],
        )
        self.assertEqual(row.sample_size, body["sample_size"])
        self.assertEqual(row.submitted_by_worker_id, "w-test")
        self.assertIsNotNone(row.measured_at)
        data = response.json()
        self.assertTrue(data["created"])
        self.assertEqual(data["draw_rate_reference"], body["draw_rate_reference"])

    def test_duplicate_submission_returns_200_no_op(self):
        """Re-posting the same (network, hash) is idempotent: 200, original row preserved."""
        body = _valid_body()
        first = self.client.post(URL, body, format="json")
        self.assertEqual(first.status_code, 201)

        original_row = NetworkCalibration.objects.get(
            network_name=body["network_name"], settings_hash=body["settings_hash"]
        )
        original_measured_at = original_row.measured_at
        original_drr = original_row.draw_rate_reference

        # Second writer arrives with a different measurement: must be ignored.
        second = self.client.post(
            URL, _valid_body(draw_rate_reference=0.71, worker_id="w-2"), format="json"
        )
        self.assertEqual(second.status_code, 200, second.content)
        self.assertFalse(second.json()["created"])

        self.assertEqual(NetworkCalibration.objects.count(), 1)
        original_row.refresh_from_db()
        self.assertEqual(original_row.measured_at, original_measured_at)
        self.assertEqual(original_row.draw_rate_reference, original_drr)
        self.assertEqual(original_row.submitted_by_worker_id, "w-test")

    def test_requires_authentication(self):
        """Calls without an API key are rejected."""
        unauth = APIClient()
        response = unauth.post(URL, _valid_body(), format="json")
        self.assertIn(response.status_code, (401, 403))

    def test_rejects_draw_rate_outside_bounds(self):
        """draw_rate_reference must lie within (0.001, 0.999)."""
        for bad in (0.0, 0.0005, 1.0, 1.5, -0.1):
            with self.subTest(draw_rate_reference=bad):
                response = self.client.post(
                    URL, _valid_body(draw_rate_reference=bad), format="json"
                )
                self.assertEqual(response.status_code, 400, (bad, response.content))

    def test_rejects_nonpositive_sample_size(self):
        """sample_size must be a positive integer."""
        response = self.client.post(URL, _valid_body(sample_size=0), format="json")
        self.assertEqual(response.status_code, 400)

    def test_rejects_negative_sem(self):
        """sem must be non-negative."""
        response = self.client.post(URL, _valid_body(sem=-0.01), format="json")
        self.assertEqual(response.status_code, 400)

    def test_rejects_missing_fields(self):
        """Missing required fields produce a 400 with field-level errors."""
        body = _valid_body()
        del body["draw_rate_reference"]
        response = self.client.post(URL, body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("draw_rate_reference", response.json())
