"""
Title: models.py — API authentication and worker key management
Description:
    Defines the WorkerAPIKey model for authenticating remote analysis workers
    and the WorkerLogUpload model that tracks session-log uploads pushed by
    workers to the maintainer-accessible object-storage bucket.
    Keys are hashed at rest; raw keys shown exactly once at creation.

Changelog:
    2026-05-06 (#15): Created WorkerAPIKey model for worker authentication
    2026-05-13 (#52): Added WorkerLogUpload for worker log uploads
"""
from django.conf import settings
from django.db import models
from rest_framework_api_key.models import AbstractAPIKey


class WorkerAPIKey(AbstractAPIKey):
    """
    API key issued to a remote analysis worker.
    Keys are hashed at rest; the raw key is shown exactly once at
    creation. The 8-char prefix is non-secret and safe to log/store.
    """
    worker_name  = models.CharField(max_length=128)
    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='issued_api_keys',
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    class Meta(AbstractAPIKey.Meta):
        verbose_name        = 'Worker API Key'
        verbose_name_plural = 'Worker API Keys'

    def __str__(self):
        """Return a human-readable identifier for this key."""
        return f"Key for {self.worker_name} ({self.prefix})"


class WorkerLogUpload(models.Model):
    """
    A session-log file uploaded by a worker for maintainer triage.

    The raw log bytes live in the configured object-storage bucket at
    ``bucket_key``; this row stores only the metadata needed to look the
    file up and a short ``host_summary`` snapshot of the worker's banner.
    """

    REASON_CRASH = 'crash'
    REASON_MANUAL = 'manual'
    REASON_CHOICES = [
        (REASON_CRASH, 'crash'),
        (REASON_MANUAL, 'manual'),
    ]

    worker = models.ForeignKey(
        WorkerAPIKey,
        on_delete=models.CASCADE,
        related_name='log_uploads',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    bucket_key = models.CharField(max_length=512)
    size_bytes = models.PositiveIntegerField()
    note = models.TextField(blank=True)
    reason = models.CharField(max_length=16, choices=REASON_CHOICES)
    worker_version = models.CharField(max_length=32, blank=True)
    host_summary = models.JSONField(default=dict)

    class Meta:
        verbose_name = 'Worker Log Upload'
        verbose_name_plural = 'Worker Log Uploads'
        ordering = ('-uploaded_at',)

    def __str__(self) -> str:
        """Return a short identifier for the admin changelist."""
        return f"{self.worker.worker_name} {self.reason} {self.uploaded_at:%Y-%m-%dT%H:%M:%SZ}"

