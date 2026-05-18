"""
Title: test_reconcile_vast_integration.py — full reconcile lifecycle
Description:
    Tick 1: pending schedule → launched (running). Simulated ~40-min
    gap (backdated launched_at) so the worker can register after launch
    then go stale. Tick 2: stale worker → instance destroyed, schedule
    done, second pending schedule launched same tick (reap-then-launch).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
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
class ReconcileLifecycleTests(TestCase):
    """Reap-then-launch composes across ticks."""

    def test_full_lifecycle(self):
        s1 = AnalysisSchedule.objects.create()
        # Tick 1: launch s1.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())
        s1.refresh_from_db()
        inst = AnalysisInstance.objects.get()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(s1.status, AnalysisSchedule.STATUS_RUNNING)

        # Simulate the ~45-min cron gap: Tick 1 effectively happened
        # ~40 min ago. The worker registered AFTER launch (last_seen
        # -20 min, i.e. after launched_at -40 min) and has since gone
        # stale relative to the 15-min cutoff → drained.
        now = timezone.now()
        AnalysisInstance.objects.filter(pk=inst.pk).update(
            launched_at=now - timedelta(minutes=40))
        WorkerHeartbeat.objects.create(worker_id="w1")
        WorkerHeartbeat.objects.filter(worker_id="w1").update(
            last_seen=now - timedelta(minutes=20))
        s2 = AnalysisSchedule.objects.create()  # queued for next run

        # Tick 2: reap s1's box (drained) then launch s2.
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK), \
             patch(_P + "destroy_instance", return_value=DESTROY_OK), \
             patch(_P + "list_instances", return_value=[]):
            call_command("reconcile_vast_analysis", stdout=StringIO())

        inst.refresh_from_db()
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.worker_id, "w1")
        self.assertEqual(s1.status, AnalysisSchedule.STATUS_DONE)
        self.assertEqual(s2.status, AnalysisSchedule.STATUS_RUNNING)
        self.assertEqual(
            AnalysisInstance.objects.filter(
                status=AnalysisInstance.STATUS_RUNNING).count(), 1)
