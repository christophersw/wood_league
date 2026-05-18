"""
Title: test_models_vast.py — AnalysisSchedule / AnalysisInstance models
Description:
    Status defaults, max_jobs fallback, FK behaviour, and the
    effective_max_jobs helper for issue #155 Sub-project A.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.test import TestCase, override_settings

from analysis.models import AnalysisInstance, AnalysisSchedule


class AnalysisScheduleModelTests(TestCase):
    """AnalysisSchedule defaults and max_jobs fallback."""

    def test_new_schedule_is_pending(self):
        """A freshly created schedule starts pending."""
        sched = AnalysisSchedule.objects.create()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)

    @override_settings(VAST_MAX_JOBS=100)
    def test_effective_max_jobs_falls_back_to_setting(self):
        """Null max_jobs uses settings.VAST_MAX_JOBS."""
        sched = AnalysisSchedule.objects.create(max_jobs=None)
        self.assertEqual(sched.effective_max_jobs(), 100)

    def test_effective_max_jobs_uses_explicit_value(self):
        """An explicit max_jobs overrides the setting."""
        sched = AnalysisSchedule.objects.create(max_jobs=42)
        self.assertEqual(sched.effective_max_jobs(), 42)


class AnalysisInstanceModelTests(TestCase):
    """AnalysisInstance defaults and schedule linkage."""

    def test_new_instance_is_launching(self):
        """A freshly created instance starts launching with no vast id."""
        sched = AnalysisSchedule.objects.create()
        inst = AnalysisInstance.objects.create(schedule=sched)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_LAUNCHING)
        self.assertIsNone(inst.vast_instance_id)
        self.assertEqual(inst.launch_worker_ids, [])

    def test_is_live_true_for_launching_and_running(self):
        """is_live is True only for non-terminal states."""
        sched = AnalysisSchedule.objects.create()
        inst = AnalysisInstance.objects.create(schedule=sched)
        self.assertTrue(inst.is_live)
        inst.status = AnalysisInstance.STATUS_DESTROYED
        self.assertFalse(inst.is_live)
        inst.status = AnalysisInstance.STATUS_FAILED
        self.assertFalse(inst.is_live)
