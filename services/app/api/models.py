"""
Title: models.py — API authentication and worker key management
Description:
    Defines the WorkerAPIKey model for authenticating remote analysis workers.
    Keys are hashed at rest; raw keys shown exactly once at creation.

Changelog:
    2026-05-06 (#15): Created WorkerAPIKey model for worker authentication
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

