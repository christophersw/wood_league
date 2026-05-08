"""
Title: models.py — System event tracking data models
Description:
    Defines the SystemEvent model for tracking system operations including game
    syncs and analysis job execution. Records event type, status, timing, and
    any associated errors or JSON details.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""

from django.db import models


class SystemEvent(models.Model):
    """Track system events like game sync and analysis job execution."""

    event_type = models.CharField(max_length=32, db_index=True)
    status = models.CharField(max_length=16, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    details = models.TextField(null=True, blank=True)  # JSON payload
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "system_events"
        ordering = ["-started_at"]
        verbose_name = "System Event"
        verbose_name_plural = "System Events"

    def __str__(self):
        """Return human-readable event description."""
        return f"{self.event_type} [{self.status}] at {self.started_at:%Y-%m-%d %H:%M}"
