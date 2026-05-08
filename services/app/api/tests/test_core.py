"""
Title: test_core.py — Core API and integration tests
Description:
    Tests for critical API functionality: authentication, job management, and service layer.

Changelog:
    2026-05-06 (#15): Created core test suite for Analysis Worker API
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import User
from api.models import WorkerAPIKey


class CoreAPITests(TestCase):
    """Test core API functionality."""

    def setUp(self):
        """Create test user and API key."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='worker@test.local', password='testpass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='test-worker',
            worker_name='test-worker',
            created_by=self.user,
        )

    def test_health_endpoint_no_auth(self):
        """Health endpoint works without authentication."""
        response = self.client.get('/api/v1/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_auth_required_for_protected_endpoints(self):
        """Protected endpoints return 403 without API key."""
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)

    def test_valid_key_grants_access(self):
        """Valid API key grants access to protected endpoints."""
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 200)

    def test_revoked_key_denied(self):
        """Revoked key is denied access."""
        self.api_key.revoked = True
        self.api_key.save()
        
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)

    def test_last_used_at_updated(self):
        """API key last_used_at is updated on each request."""
        self.assertIsNone(self.api_key.last_used_at)
        
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        self.client.get('/api/v1/jobs/status/')
        
        self.api_key.refresh_from_db()
        self.assertIsNotNone(self.api_key.last_used_at)

    def test_invalid_key_denied(self):
        """Invalid API key returns 403."""
        self.client.credentials(HTTP_X_API_KEY='invalid-key-abc123')
        response = self.client.get('/api/v1/jobs/status/')
        self.assertEqual(response.status_code, 403)
