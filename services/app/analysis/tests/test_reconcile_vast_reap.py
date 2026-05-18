"""
Title: test_reconcile_vast_reap.py — reconcile reap pass
Description:
    hard_deadline destroy; stale-heartbeat drained destroy; worker
    binding; never-registered failure; destroy-retry on failure;
    schedule recovery; orphan-by-label. vast_dispatch is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.management.commands.reconcile_vast_analysis import _reap

OK = {"ok": True, "status_code": 200, "message": "destroyed"}
FAIL = {"ok": False, "status_code": 0, "message": "boom"}


@override_settings(VAST_API_KEY="k", VAST_WORKER_STALE_MINUTES=15)
class ReapTests(TestCase):
    """Reap destroys finished/overdue instances and recovers schedules."""

    def _live_instance(self, **kw):
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_RUNNING)
        defaults = dict(
            schedule=sched, status=AnalysisInstance.STATUS_RUNNING,
            vast_instance_id="555",
            launched_at=timezone.now() - timedelta(hours=1),
            hard_deadline=timezone.now() + timedelta(hours=5),
            launch_worker_ids=[],
        )
        defaults.update(kw)
        return AnalysisInstance.objects.create(**defaults)

    def test_past_hard_deadline_destroyed(self):
        """An instance past hard_deadline is destroyed unconditionally."""
        inst = self._live_instance(
            hard_deadline=timezone.now() - timedelta(minutes=1))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            n = _reap("k")
        inst.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertIsNotNone(inst.destroyed_at)

    def test_stale_heartbeat_drained_destroyed(self):
        """Bound worker heartbeat stale → drained → destroyed; sched done."""
        inst = self._live_instance()
        WorkerHeartbeat.objects.create(worker_id="w-new")
        WorkerHeartbeat.objects.filter(worker_id="w-new").update(
            last_seen=timezone.now() - timedelta(minutes=30))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.worker_id, "w-new")
        self.assertEqual(inst.schedule.status, AnalysisSchedule.STATUS_DONE)

    def test_pre_launch_worker_not_bound(self):
        """A heartbeat present at launch is NOT bound (not this run).

        Uses a recent launched_at (inside the stale window) so the
        non-binding is what keeps it alive, not the never-registered
        timer.
        """
        inst = self._live_instance(
            launch_worker_ids=["w-old"],
            launched_at=timezone.now() - timedelta(minutes=5))
        WorkerHeartbeat.objects.create(worker_id="w-old")
        WorkerHeartbeat.objects.filter(worker_id="w-old").update(
            last_seen=timezone.now() - timedelta(minutes=2))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertIsNone(inst.worker_id)
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)

    def test_worker_never_registered_fails(self):
        """No worker bound and past stale window from launch → failed."""
        inst = self._live_instance(
            launched_at=timezone.now() - timedelta(minutes=30))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.schedule.status, AnalysisSchedule.STATUS_FAILED)

    def test_destroy_failure_leaves_non_terminal_for_retry(self):
        """A failed vast destroy keeps the row live for the next tick."""
        inst = self._live_instance(
            hard_deadline=timezone.now() - timedelta(minutes=1))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=FAIL), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_RUNNING)

    def test_orphan_by_label_destroyed(self):
        """A live vast instance whose AnalysisInstance is terminal is killed."""
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_DONE)
        AnalysisInstance.objects.create(
            schedule=sched, status=AnalysisInstance.STATUS_DESTROYED,
            vast_instance_id="900")
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK) as d, \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances",
                   return_value=[{"id": 900, "label": f"wl-sched-{sched.id}",
                                  "actual_status": "running"}]):
            _reap("k")
        d.assert_any_call(api_key="k", vast_instance_id="900")

    def test_never_registered_fires_with_prelaunch_snapshot(self):
        """Non-empty launch_worker_ids must NOT suppress never-registered."""
        inst = self._live_instance(
            launch_worker_ids=["w-old"],
            launched_at=timezone.now() - timedelta(minutes=30))
        WorkerHeartbeat.objects.create(worker_id="w-old")
        WorkerHeartbeat.objects.filter(worker_id="w-old").update(
            last_seen=timezone.now() - timedelta(minutes=40))
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.schedule.status,
                         AnalysisSchedule.STATUS_FAILED)

    def test_bound_worker_missing_heartbeat_is_drained(self):
        """worker_id bound but no heartbeat row → drained → destroyed."""
        inst = self._live_instance(worker_id="w-gone")
        with patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.destroy_instance", return_value=OK), \
             patch("analysis.management.commands.reconcile_vast_analysis."
                   "vast_dispatch.list_instances", return_value=[]):
            _reap("k")
        inst.refresh_from_db()
        self.assertEqual(inst.status, AnalysisInstance.STATUS_DESTROYED)
        self.assertEqual(inst.schedule.status,
                         AnalysisSchedule.STATUS_DONE)
