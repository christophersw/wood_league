"""
Title: test_log_upload.py — Worker log upload endpoint and admin tests
Description:
    Covers the multipart upload endpoint (happy path, auth, size limit,
    rate limit, force bypass) and the admin download / bulk-zip actions
    introduced for issue #52.

Changelog:
    2026-05-13 (#52): Initial creation.
"""
from __future__ import annotations

import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from api.models import WorkerAPIKey, WorkerLogUpload


def _make_log(size: int = 64) -> io.BytesIO:
    """Return an in-memory binary log file of the requested size."""
    buf = io.BytesIO(b'x' * size)
    buf.name = 'worker.log'
    return buf


@override_settings(WORKER_LOG_BUCKET='test-bucket', WORKER_LOG_RATE_LIMIT_SECONDS=0)
class WorkerLogUploadEndpointTests(TestCase):
    """Test POST /api/v1/worker/logs/."""

    def setUp(self) -> None:
        """Create a staff user, an API key, and an authenticated APIClient."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='log@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='logger', worker_name='logger', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

    def test_upload_happy_path(self) -> None:
        """A valid multipart POST creates a row and streams to the bucket."""
        metadata = json.dumps({
            'reason': 'manual',
            'worker_version': '0.5.0',
            'host_summary': {'system': 'Darwin'},
        })
        with patch('api.log_upload_view.upload_stream') as stub:
            response = self.client.post(
                '/api/v1/worker/logs/',
                {
                    'log': _make_log(64),
                    'note': 'hello',
                    'metadata': metadata,
                },
                format='multipart',
            )
        self.assertEqual(response.status_code, 201)
        stub.assert_called_once()
        row = WorkerLogUpload.objects.get()
        self.assertEqual(row.worker, self.api_key)
        self.assertEqual(row.reason, 'manual')
        self.assertEqual(row.note, 'hello')
        self.assertEqual(row.worker_version, '0.5.0')
        self.assertEqual(row.host_summary, {'system': 'Darwin'})
        self.assertEqual(row.size_bytes, 64)
        self.assertTrue(row.bucket_key.endswith('.log'))

    def test_upload_requires_auth(self) -> None:
        """Without an API key the endpoint returns 401 or 403."""
        self.client.credentials()
        response = self.client.post(
            '/api/v1/worker/logs/',
            {'log': _make_log(8)},
            format='multipart',
        )
        self.assertIn(response.status_code, (401, 403))

    def test_upload_rejects_oversize_log(self) -> None:
        """Files larger than WORKER_LOG_MAX_BYTES are rejected with 413."""
        with override_settings(WORKER_LOG_MAX_BYTES=16):
            with patch('api.log_upload_view.upload_stream') as stub:
                response = self.client.post(
                    '/api/v1/worker/logs/',
                    {'log': _make_log(64), 'metadata': '{}'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 413)
        stub.assert_not_called()
        self.assertEqual(WorkerLogUpload.objects.count(), 0)

    def test_upload_missing_log_part_returns_400(self) -> None:
        """A POST with no ``log`` file part returns 400."""
        response = self.client.post(
            '/api/v1/worker/logs/',
            {'note': 'no file'},
            format='multipart',
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_rate_limited_per_worker(self) -> None:
        """A second upload within the cooldown window returns 429."""
        WorkerLogUpload.objects.create(
            worker=self.api_key,
            bucket_key='prev/key.log',
            size_bytes=10,
            reason='manual',
        )
        with override_settings(WORKER_LOG_RATE_LIMIT_SECONDS=60):
            with patch('api.log_upload_view.upload_stream') as stub:
                response = self.client.post(
                    '/api/v1/worker/logs/',
                    {'log': _make_log(8), 'metadata': '{}'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 429)
        stub.assert_not_called()

    def test_upload_force_bypasses_rate_limit(self) -> None:
        """``?force=true`` lets a crash upload run despite the cooldown."""
        WorkerLogUpload.objects.create(
            worker=self.api_key,
            bucket_key='prev/key.log',
            size_bytes=10,
            reason='manual',
        )
        with override_settings(WORKER_LOG_RATE_LIMIT_SECONDS=60):
            with patch('api.log_upload_view.upload_stream'):
                response = self.client.post(
                    '/api/v1/worker/logs/?force=true',
                    {'log': _make_log(8), 'metadata': '{"reason": "crash"}'},
                    format='multipart',
                )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(WorkerLogUpload.objects.count(), 2)

    def test_upload_disabled_when_bucket_unset(self) -> None:
        """A blank ``WORKER_LOG_BUCKET`` returns 503."""
        with override_settings(WORKER_LOG_BUCKET=''):
            response = self.client.post(
                '/api/v1/worker/logs/',
                {'log': _make_log(8)},
                format='multipart',
            )
        self.assertEqual(response.status_code, 503)


@override_settings(WORKER_LOG_BUCKET='test-bucket', WORKER_LOG_PRESIGN_TTL_SECONDS=900)
class WorkerLogUploadAdminTests(TestCase):
    """Test the Django-admin download and bulk-zip actions."""

    def setUp(self) -> None:
        """Create a staff user, an API key, and a WorkerLogUpload row."""
        self.client = APIClient()
        self.staff = User.objects.create_user(
            email='admin@test.local', password='pass', is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(user=self.staff)
        self.api_key, _ = WorkerAPIKey.objects.create_key(
            name='admin-logger', worker_name='admin-logger', created_by=self.staff
        )
        self.upload = WorkerLogUpload.objects.create(
            worker=self.api_key,
            bucket_key='hashprefix/2026-05-13.log',
            size_bytes=128,
            reason='manual',
            note='note text',
        )

    def test_download_view_redirects_to_presigned_url(self) -> None:
        """The per-row download view returns a 302 to the presigned URL."""
        self.client.logout()
        self.client.force_login(self.staff)
        fake_url = 'https://bucket.example.com/signed?token=abc'
        with patch('api.log_admin.presigned_get_url', return_value=fake_url) as stub:
            response = self.client.get(
                f'/django-admin/api/workerlogupload/{self.upload.id}/download/'
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], fake_url)
        stub.assert_called_once_with('hashprefix/2026-05-13.log', ttl_seconds=900)

    def test_retention_command_deletes_old_rows_and_objects(self) -> None:
        """``prune_worker_logs`` removes rows older than the threshold."""
        from django.core.management import call_command

        stale = WorkerLogUpload.objects.create(
            worker=self.api_key,
            bucket_key='stale/key.log',
            size_bytes=64,
            reason='manual',
        )
        WorkerLogUpload.objects.filter(pk=stale.pk).update(
            uploaded_at=timezone.now() - timedelta(days=120)
        )
        with patch('api.log_storage.delete_object') as stub:
            call_command('prune_worker_logs', '--days', '30')
        stub.assert_called_once_with('stale/key.log')
        self.assertFalse(WorkerLogUpload.objects.filter(pk=stale.pk).exists())
        # The fresh row from setUp must survive.
        self.assertTrue(WorkerLogUpload.objects.filter(pk=self.upload.pk).exists())
