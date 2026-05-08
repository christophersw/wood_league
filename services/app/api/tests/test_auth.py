"""
Title: test_auth.py — API authentication tests
Description:
    Tests API key authentication, missing keys, invalid keys, revoked keys,
    and last_used_at tracking.

Changelog:
    2026-05-06 (#15): Created test suite for API key authentication
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import User
from api.models import WorkerAPIKey


class APIAuthTests(TestCase):
    """Test API key authentication on protected endpoints."""

    def setUp(self):
        """Create test user and API key."""
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='worker@test.local',
            password='testpass123'
        )
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='test-worker',
            worker_name='test-worker',
            created_by=self.user,
        )

    def test_health_no_auth_required(self):
        """GET /api/v1/health/ works without API key."""
        response = self.client.get('/api/v1/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_missing_api_key_returns_403(self):
        """Protected endpoints return 403 when no API key."""
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)

    def test_invalid_api_key_returns_403(self):
        """Protected endpoints return 403 with invalid API key."""
        self.client.credentials(HTTP_X_API_KEY='invalid-key-xyz')
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)

    def test_revoked_key_returns_403(self):
        """Revoked API key returns 403."""
        self.api_key.revoked = True
        self.api_key.save()
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)

    def test_valid_key_returns_200(self):
        """Valid API key grants access to protected endpoint."""
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 200)

    def test_last_used_at_updated(self):
        """last_used_at is updated on authenticated requests."""
        self.assertIsNone(self.api_key.last_used_at)
        
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        before = timezone.now()
        self.client.get('/api/v1/jobs/status/')
        after = timezone.now()
        
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)
        self.assertGreaterEqual(self.api_key.last_used_at, before)
        self.assertLessEqual(self.api_key.last_used_at, after)
