"""
Title: test_runpod_admin.py — Tests for the admin RunPod start-pod endpoint
Description:
    Covers both the thin REST client (app.runpod_client.start_pod) and the
    admin view (analysis.views.runpod_start_view) added for issue #83:

    Client:
      * 2xx response → ok=True
      * 4xx response → ok=False, WARNING logged, no raise
      * Network error → ok=False, WARNING logged, no raise

    View:
      * anonymous → login redirect (302)
      * authenticated non-staff (role=player) → 403
      * staff + RUNPOD_ENABLED=False → 404
      * staff + creds missing → 400 JSON
      * staff + creds present → calls start_pod once with the configured
        pod id and returns the structured JSON
      * GET → 405

Changelog:
    2026-05-14: Initial — issue #83.
"""
from __future__ import annotations

import logging
import uuid
from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from app.runpod_client import start_pod


def _make_user(role: str) -> User:
    """Create a User with the given role and a unique email.

    Args:
        role: User role string, e.g. ``"admin"`` or ``"player"``.

    Returns:
        User: A saved User instance.
    """
    return User.objects.create_user(
        email=f"{role}-rp-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only password
        role=role,
    )


class StartPodClientTests(TestCase):
    """Unit tests for app.runpod_client.start_pod."""

    def test_2xx_returns_ok_true_with_bearer_header(self):
        """A 200 response must yield ok=True and send the Bearer token."""
        fake_response = MagicMock(status_code=200, text="{}")
        with patch("app.runpod_client.httpx.post", return_value=fake_response) as mock_post:
            result = start_pod("pod-xyz", "secret-key")

        self.assertTrue(result["ok"])
        self.assertEqual(result["status_code"], 200)
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://rest.runpod.io/v1/pods/pod-xyz/start")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-key")

    def test_4xx_returns_ok_false_and_logs_warning(self):
        """A 401 response must yield ok=False, log WARNING, and not raise."""
        fake_response = MagicMock(status_code=401, text="unauthorized", reason_phrase="Unauthorized")
        with patch("app.runpod_client.httpx.post", return_value=fake_response):
            with self.assertLogs("app.runpod_client", level="WARNING") as cm:
                result = start_pod("pod-xyz", "bad-key")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 401)
        self.assertTrue(any("non-2xx" in line for line in cm.output))

    def test_network_error_returns_ok_false_and_logs_warning(self):
        """A connect error must yield ok=False with status_code=0, log WARNING, no raise."""
        with patch(
            "app.runpod_client.httpx.post",
            side_effect=httpx.ConnectError("boom"),
        ):
            with self.assertLogs("app.runpod_client", level="WARNING") as cm:
                result = start_pod("pod-xyz", "k")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 0)
        self.assertIn("boom", result["message"])
        self.assertTrue(any("network error" in line for line in cm.output))

    def test_body_is_truncated_in_log(self):
        """Long response bodies must be truncated when surfaced in the log message."""
        long_body = "x" * 2000
        fake_response = MagicMock(status_code=500, text=long_body, reason_phrase="err")
        with patch("app.runpod_client.httpx.post", return_value=fake_response):
            # Suppress propagation of WARNING during this assertion.
            logging.getLogger("app.runpod_client").setLevel(logging.WARNING)
            result = start_pod("pod-xyz", "k")
        # The returned message echoes the truncated body, so its length must
        # be bounded by the 500-char limit plus the truncation marker.
        self.assertLess(len(result["message"]), 600)
        self.assertIn("truncated", result["message"])


@override_settings(
    RUNPOD_ENABLED=True,
    RUNPOD_API_KEY="test-key",
    RUNPOD_WORKER_POD_ID="pod-abc",
)
class RunpodStartViewTests(TestCase):
    """Tests for the analysis:runpod_start admin endpoint."""

    def setUp(self):
        """Resolve the endpoint URL once per test."""
        self.url = reverse("analysis:runpod_start")

    def test_anonymous_user_is_redirected(self):
        """Anonymous POST must redirect (302) — login_required behaviour."""
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_non_staff_user_is_forbidden(self):
        """Authenticated non-staff (role=player) must receive 403."""
        player = _make_user("player")
        self.client.force_login(player)
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 403)

    @override_settings(RUNPOD_ENABLED=False)
    def test_disabled_returns_404(self):
        """When RUNPOD_ENABLED is False the route must 404 for staff too."""
        admin = _make_user("admin")
        self.client.force_login(admin)
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 404)

    @override_settings(RUNPOD_API_KEY="", RUNPOD_WORKER_POD_ID="")
    def test_missing_creds_returns_400_json(self):
        """Missing creds must return 400 with a JSON message and no RunPod call."""
        admin = _make_user("admin")
        self.client.force_login(admin)
        with patch("analysis.views.start_pod") as mock_start:
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertIn("not configured", body["message"])
        mock_start.assert_not_called()

    def test_staff_happy_path_calls_start_pod_once(self):
        """Staff POST with creds present must call start_pod once with the configured pod id."""
        admin = _make_user("admin")
        self.client.force_login(admin)
        fake_result = {"ok": True, "status_code": 200, "message": "started"}
        with patch("analysis.views.start_pod", return_value=fake_result) as mock_start:
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), fake_result)
        mock_start.assert_called_once_with("pod-abc", "test-key")

    def test_staff_runpod_failure_returns_502(self):
        """When start_pod returns ok=False the view must respond with HTTP 502."""
        admin = _make_user("admin")
        self.client.force_login(admin)
        fake_result = {"ok": False, "status_code": 500, "message": "boom"}
        with patch("analysis.views.start_pod", return_value=fake_result):
            resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json(), fake_result)

    def test_get_is_not_allowed(self):
        """GET must be rejected with 405 (require_POST decorator)."""
        admin = _make_user("admin")
        self.client.force_login(admin)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 405)
