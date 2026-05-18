"""
Title: test_scheduling_integration.py — B→A composition
Description:
    A rule created via the admin page → reconcile Step 0 materializes a
    pending AnalysisSchedule → A's launch (vast mocked) consumes it.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

import uuid
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from analysis.models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
)

OFFER = {"id": 22, "gpu_name": "L40S", "dph_total": 0.90}
CREATE_OK = {"ok": True, "status_code": 200, "message": "created",
             "vast_instance_id": "98765"}
DESTROY_OK = {"ok": True, "status_code": 200, "message": "destroyed"}
_P = "analysis.management.commands.reconcile_vast_analysis.vast_dispatch."


@override_settings(VAST_ENABLED=True, VAST_API_KEY="k",
                   VAST_TEMPLATE_HASH="HASH", VAST_CAMPAIGN_ID="c",
                   VAST_MAX_JOBS=100, VAST_OFFER_GPU_NAME="L40S",
                   VAST_OFFER_MAX_DPH=1.5, VAST_HARD_DEADLINE_HOURS=6,
                   VAST_WORKER_STALE_MINUTES=15)
class SchedulingToOrchestratorTests(TestCase):
    """A UI-created rule flows through Step 0 into A's launch."""

    def test_rule_materializes_then_launches(self):
        admin = User.objects.create_user(
            email=f"a-{uuid.uuid4().hex[:6]}@test",
            password="x", role="admin")  # noqa: S106
        self.client.force_login(admin)

        # Create an always-due rule through the real admin page.
        self.client.post(reverse("analysis:rule_create"), {
            "name": "min", "crontab": "* * * * *", "timezone": "UTC",
            "max_jobs": "", "note": "", "enabled": "on"})
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 1)

        # Reconcile tick: Step 0 materializes, A's launch consumes it.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())

        sched = AnalysisSchedule.objects.get()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_RUNNING)
        self.assertIsNotNone(sched.recurring_rule)
        inst = AnalysisInstance.objects.get()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(inst.vast_instance_id, "98765")
