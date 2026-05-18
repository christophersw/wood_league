"""
Title: reconcile_vast_analysis.py — idempotent vast.ai reconcile cron
Description:
    Run every 45 min by a Railway cron service. Holds no long-lived
    process and no in-memory state: each run re-derives "what should be
    true" from AnalysisSchedule + AnalysisInstance and converges.
    Order each run: (1) REAP — destroy any instance past hard_deadline
    or whose worker heartbeat went stale (batch drained); recover stuck
    schedules; destroy orphans by label. (2) LAUNCH — if no instance is
    live and a pending schedule exists, provision one.
    Gated by settings.VAST_ENABLED (no-op when off), exactly like
    RUNPOD_ENABLED gates the start-pod endpoint.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from analysis.models import (
    AnalysisInstance, AnalysisSchedule, WorkerHeartbeat,
)
from analysis.services import vast_dispatch

_LABEL_PREFIX = "wl-sched-"


def _label_for(schedule_id: int) -> str:
    """Return the vast instance label for a schedule (orphan discovery)."""
    return f"{_LABEL_PREFIX}{schedule_id}"


def _bind_worker(inst: AnalysisInstance) -> None:
    """Bind the first post-launch WorkerHeartbeat to this instance.

    Only a worker that heartbeated at/after launch and was NOT present
    at launch is this run's worker (≤1-instance invariant makes this
    unambiguous). Mutates and saves ``inst.worker_id`` when found.
    """
    if inst.worker_id or not inst.launched_at:
        return
    known = set(inst.launch_worker_ids or [])
    hb = (
        WorkerHeartbeat.objects
        .exclude(worker_id__in=known)
        .filter(last_seen__gte=inst.launched_at)
        .order_by("last_seen")
        .first()
    )
    if hb is not None:
        inst.worker_id = hb.worker_id
        inst.save(update_fields=["worker_id"])


def _is_drained(inst: AnalysisInstance, stale_cutoff) -> bool:
    """Return True when the instance's batch is drained.

    Drained = bound worker heartbeat is stale (worker exited) OR the
    bound heartbeat reports its job cap done.
    """
    if not inst.worker_id:
        return False
    hb = WorkerHeartbeat.objects.filter(worker_id=inst.worker_id).first()
    if hb is None:
        return False
    if hb.last_seen < stale_cutoff:
        return True
    return (hb.batch_total is not None
            and hb.batch_processed >= hb.batch_total)


def _destroy(inst: AnalysisInstance, api_key: str) -> bool:
    """Destroy the vast box for ``inst``. Return True iff destroyed.

    On success: status=destroyed + destroyed_at stamped. On failure:
    row left non-terminal so the next tick retries.
    """
    if not inst.vast_instance_id:
        # Nothing was ever created — mark terminal without a vast call.
        inst.status = AnalysisInstance.STATUS_FAILED
        inst.save(update_fields=["status"])
        return False
    result = vast_dispatch.destroy_instance(
        api_key=api_key, vast_instance_id=inst.vast_instance_id)
    if not result["ok"]:
        return False
    inst.status = AnalysisInstance.STATUS_DESTROYED
    inst.destroyed_at = timezone.now()
    inst.save(update_fields=["status", "destroyed_at"])
    return True


def _recover_schedules() -> None:
    """Settle any `running` schedule whose latest instance is terminal."""
    for sched in AnalysisSchedule.objects.filter(
            status=AnalysisSchedule.STATUS_RUNNING):
        last = sched.instances.order_by("-created_at").first()
        if last is None or last.is_live:
            continue
        sched.status = (
            AnalysisSchedule.STATUS_DONE
            if last.status == AnalysisInstance.STATUS_DESTROYED
            else AnalysisSchedule.STATUS_FAILED
        )
        sched.save(update_fields=["status"])


class Command(BaseCommand):
    """Idempotent reap-then-launch reconcile for vast.ai analysis runs."""

    help = (
        "Reconcile vast.ai analysis instances: destroy finished/overdue "
        "boxes, then launch one if a run is scheduled. Idempotent; safe "
        "to run on a 45-minute cron. No-op unless VAST_ENABLED."
    )

    def handle(self, *args, **options):
        """Entry point. No-op when disabled or unconfigured.

        Parameters:
            args: Positional arguments (unused).
            options (dict): Parsed CLI options (none defined; unused).

        Side effects:
            Writes one status line to stdout. When enabled + configured:
            runs the reap pass then the launch pass (Tasks 6, 7).
        """
        if not getattr(settings, "VAST_ENABLED", False):
            self.stdout.write("vast reconcile disabled (VAST_ENABLED off)")
            return
        if not getattr(settings, "VAST_API_KEY", ""):
            self.stdout.write(
                "vast reconcile: VAST_API_KEY not configured — skipping")
            return
        api_key = settings.VAST_API_KEY
        reaped = _reap(api_key)
        launched = _launch(api_key)
        self.stdout.write(
            f"vast reconcile done: reaped={reaped} launched={launched}")


def _reap(api_key: str) -> int:
    """Destroy finished/overdue instances; recover schedules; kill orphans.

    Returns:
        int: number of instances destroyed this run.
    """
    now = timezone.now()
    stale_cutoff = now - timedelta(
        minutes=settings.VAST_WORKER_STALE_MINUTES)
    destroyed = 0

    for inst in AnalysisInstance.objects.filter(
            status__in=AnalysisInstance._LIVE_STATES):
        _bind_worker(inst)
        overdue = inst.hard_deadline is not None and now >= inst.hard_deadline
        drained = _is_drained(inst, stale_cutoff)
        never_registered = (
            not inst.worker_id and inst.launched_at is not None
            and inst.launched_at < stale_cutoff
            and not inst.launch_worker_ids
        )
        if not (overdue or drained or never_registered):
            continue
        if _destroy(inst, api_key):
            destroyed += 1
            if never_registered and not overdue and not drained:
                inst.schedule.status = AnalysisSchedule.STATUS_FAILED
                inst.schedule.save(update_fields=["status"])

    _recover_schedules()

    # Orphan-by-label: kill any live vast instance whose AnalysisInstance
    # is terminal/absent (covers a lost create-time DB write).
    terminal_or_absent = []
    for vinst in vast_dispatch.list_instances(api_key=api_key):
        label = vinst.get("label") or ""
        if not label.startswith(_LABEL_PREFIX):
            continue
        try:
            sched_id = int(label[len(_LABEL_PREFIX):])
        except ValueError:
            continue
        rec = (
            AnalysisInstance.objects
            .filter(schedule_id=sched_id,
                    vast_instance_id=str(vinst.get("id")))
            .first()
        )
        if rec is None or not rec.is_live:
            terminal_or_absent.append(str(vinst.get("id")))
    for vid in terminal_or_absent:
        if vast_dispatch.destroy_instance(
                api_key=api_key, vast_instance_id=vid)["ok"]:
            destroyed += 1

    return destroyed


def _launch(api_key: str) -> int:
    """Launch one instance if scheduled and none live. Implemented in Task 7.

    Returns:
        int: 1 if an instance was launched, else 0.
    """
    return 0
