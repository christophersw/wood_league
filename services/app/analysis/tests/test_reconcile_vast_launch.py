"""
Title: test_reconcile_vast_launch.py — reconcile launch pass
Description:
    FIFO pending pick; ≤1-instance guard; launching-row-before-create;
    no-offer path; create success/failure; worker-id snapshot; env +
    label payload. vast_dispatch is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.services.vast_dispatch import NoVastOfferError
from analysis.management.commands.reconcile_vast_analysis import _launch

OFFER = {"id": 22, "gpu_name": "L40S", "dph_total": 0.90}
CREATE_OK = {"ok": True, "status_code": 200, "message": "created",
             "vast_instance_id": "98765"}
CREATE_FAIL = {"ok": False, "status_code": 400, "message": "bad",
               "vast_instance_id": None}

_P = "analysis.management.commands.reconcile_vast_analysis.vast_dispatch."


@override_settings(VAST_API_KEY="k", VAST_TEMPLATE_HASH="HASH",
                   VAST_CAMPAIGN_ID="camp1", VAST_MAX_JOBS=100,
                   VAST_OFFER_GPU_NAME="L40S", VAST_OFFER_MAX_DPH=1.5,
                   VAST_HARD_DEADLINE_HOURS=6)
class LaunchTests(TestCase):
    """Launch provisions exactly one instance for the oldest pending row."""

    def test_no_pending_is_noop(self):
        """No pending schedule → nothing launched."""
        self.assertEqual(_launch("k"), 0)
        self.assertEqual(AnalysisInstance.objects.count(), 0)

    def test_live_instance_blocks_launch(self):
        """An existing live instance prevents a second launch."""
        s = AnalysisSchedule.objects.create()
        AnalysisInstance.objects.create(
            schedule=s, status=AnalysisInstance.STATUS_RUNNING)
        AnalysisSchedule.objects.create()  # a fresh pending one
        self.assertEqual(_launch("k"), 0)
        self.assertEqual(
            AnalysisInstance.objects.filter(
                status=AnalysisInstance.STATUS_LAUNCHING).count(), 0)

    def test_success_launches_and_sets_fields(self):
        """Happy path: instance running, schedule running, fields set."""
        sched = AnalysisSchedule.objects.create()
        WorkerHeartbeat.objects.create(worker_id="pre-existing")
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance",
                   return_value=CREATE_OK) as create:
            n = _launch("k")
        sched.refresh_from_db()
        inst = AnalysisInstance.objects.get()
        self.assertEqual(n, 1)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)
        self.assertEqual(inst.vast_instance_id, "98765")
        self.assertEqual(inst.offer_dph, 0.90)
        self.assertIsNotNone(inst.hard_deadline)
        self.assertEqual(inst.launch_worker_ids, ["pre-existing"])
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_RUNNING)
        _, kw = create.call_args
        self.assertEqual(kw["label"], f"wl-sched-{sched.id}")
        self.assertEqual(kw["env"]["WL_CAMPAIGN_ID"], "camp1")
        self.assertEqual(kw["env"]["WLW_MAX_JOBS"], "100")
        self.assertEqual(kw["env"]["WL_SCHEDULE_ID"], str(sched.id))

    def test_fifo_oldest_pending_first(self):
        """The oldest pending schedule is the one launched."""
        old = AnalysisSchedule.objects.create()
        AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_OK):
            _launch("k")
        old.refresh_from_db()
        self.assertEqual(old.status, AnalysisSchedule.STATUS_RUNNING)

    def test_no_offer_marks_instance_failed_schedule_stays_pending(self):
        """NoVastOfferError → launching row failed, schedule still pending."""
        sched = AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer",
                   side_effect=NoVastOfferError("none")):
            n = _launch("k")
        sched.refresh_from_db()
        self.assertEqual(n, 0)
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(
            AnalysisInstance.objects.get().status,
            AnalysisInstance.STATUS_FAILED)

    def test_create_failure_marks_both_failed(self):
        """vast create failure → instance failed, schedule failed."""
        sched = AnalysisSchedule.objects.create()
        with patch(_P + "search_cheapest_offer", return_value=OFFER), \
             patch(_P + "create_instance", return_value=CREATE_FAIL):
            n = _launch("k")
        sched.refresh_from_db()
        self.assertEqual(n, 0)
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_FAILED)
        self.assertEqual(
            AnalysisInstance.objects.get().status,
            AnalysisInstance.STATUS_FAILED)
