"""
Title: admin.py — Analysis admin configuration
Description:
    Django admin interface configuration for game analysis models including
    GameAnalysis, Lc0GameAnalysis, AnalysisJob, and WorkerHeartbeat.

Changelog:
    2026-05-18: Register AnalysisSchedule/AnalysisInstance (#155).
    2026-05-08: Added file header to meet documentation standards
"""
from django.contrib import admin

from .models import AnalysisInstance, AnalysisSchedule


@admin.register(AnalysisSchedule)
class AnalysisScheduleAdmin(admin.ModelAdmin):
    """Operator window + insert point for run-intent rows."""

    list_display = ("id", "status", "max_jobs", "created_at")
    list_filter = ("status",)
    readonly_fields = ("created_at",)


@admin.register(AnalysisInstance)
class AnalysisInstanceAdmin(admin.ModelAdmin):
    """Read-mostly live/teardown view of launched vast instances."""

    list_display = (
        "id", "schedule", "status", "vast_instance_id",
        "offer_dph", "launched_at", "hard_deadline", "destroyed_at",
    )
    list_filter = ("status",)
    readonly_fields = (
        "schedule", "created_at", "vast_instance_id", "launched_at",
        "hard_deadline", "destroyed_at", "offer_dph",
        "launch_worker_ids", "worker_id",
    )
