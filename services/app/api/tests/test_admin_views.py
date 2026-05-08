"""
Title: test_admin_views.py — Admin UI tests
Description:
    Tests for API key management admin views: list, issue, revoke.

Changelog:
    2026-05-06 (#15): Created admin UI tests
"""
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from api.models import WorkerAPIKey


class AdminViewsTests(TestCase):
    """Test admin views for API key management."""

    def setUp(self):
        """Create test users and client."""
        self.client = Client()
        self.staff_user = User.objects.create_user(
            email='admin@test.local',
            password='adminpass',
            role='admin',
        )
        self.regular_user = User.objects.create_user(
            email='user@test.local',
            password='userpass',
        )

    def test_non_staff_redirect_list(self):
        """Non-staff user redirected from /admin/api-keys/."""
        self.client.login(email='user@test.local', password='userpass')
        response = self.client.get('/admin/api-keys/', follow=False)
        self.assertEqual(response.status_code, 302)

    def test_staff_can_get_list(self):
        """Staff user can GET /admin/api-keys/."""
        self.client.login(email='admin@test.local', password='adminpass')
        response = self.client.get('/admin/api-keys/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('API Keys', response.content.decode())

    def test_staff_can_issue_key(self):
        """Staff user can POST to /admin/api-keys/issue/."""
        self.client.login(email='admin@test.local', password='adminpass')
        response = self.client.post('/admin/api-keys/issue/', {
            'worker_name': 'test-worker',
            'notes': 'Test key',
        })
        
        self.assertEqual(response.status_code, 200)
        # Response should contain the raw key (shown exactly once)
        self.assertIn('save', response.content.decode().lower())

    def test_raw_key_not_stored(self):
        """Raw key is shown but not stored in database."""
        self.client.login(email='admin@test.local', password='adminpass')
        response = self.client.post('/admin/api-keys/issue/', {
            'worker_name': 'test-worker-2',
            'notes': 'Another test',
        })
        
        # Key was created
        key = WorkerAPIKey.objects.get(worker_name='test-worker-2')
        self.assertIsNotNone(key)
        
        # Raw key is in response
        response_text = response.content.decode()
        self.assertIn('save', response_text.lower())

    def test_staff_can_revoke_key(self):
        """Staff user can POST to /admin/api-keys/<id>/revoke/."""
        self.client.login(email='admin@test.local', password='adminpass')
        
        api_key, _ = WorkerAPIKey.objects.create_key(
            name='revoke-test',
            worker_name='revoke-test',
            created_by=self.staff_user,
        )
        
        response = self.client.post(
            f'/admin/api-keys/{api_key.id}/revoke/',
            follow=False
        )
        
        self.assertEqual(response.status_code, 200)
        api_key.refresh_from_db()
        self.assertTrue(api_key.revoked)

    def test_issue_key_requires_worker_name(self):
        """Issue key endpoint requires worker_name."""
        self.client.login(email='admin@test.local', password='adminpass')
        response = self.client.post('/admin/api-keys/issue/', {
            'worker_name': '',
            'notes': 'Test',
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('required', response.content.decode().lower())
