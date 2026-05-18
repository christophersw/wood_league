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

    Special case: when ``inst`` has no ``vast_instance_id`` (nothing was
    ever created), the row is marked STATUS_FAILED and False is returned
    — i.e. a False return can still mutate the row.
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


def _reap_decision(inst: AnalysisInstance, now, stale_cutoff) -> str | None:
    """Return why ``inst`` should be reaped, or None to keep it.

    Reasons (priority order): ``"overdue"`` (past hard_deadline,
    unconditional), ``"drained"`` (worker exited / cap done),
    ``"never_registered"`` (launched into an empty-worker environment
    and no worker ever appeared within the stale window).
    """
    if inst.hard_deadline is not None and now >= inst.hard_deadline:
        return "overdue"
    if _is_drained(inst, stale_cutoff):
        return "drained"
    if (not inst.worker_id and not inst.launch_worker_ids
            and inst.launched_at is not None
            and inst.launched_at < stale_cutoff):
        return "never_registered"
    return None


def _reap_one(inst: AnalysisInstance, api_key: str, now,
              stale_cutoff) -> int:
    """Reap a single live instance if warranted. Return 1 if destroyed.

    Binds the worker first (so drained detection can fire), then acts on
    the reap decision. A ``never_registered`` reap also fails the
    schedule (the run never actually started).
    """
    _bind_worker(inst)
    reason = _reap_decision(inst, now, stale_cutoff)
    if reason is None:
        return 0
    if not _destroy(inst, api_key):
        return 0
    if reason == "never_registered":
        inst.schedule.status = AnalysisSchedule.STATUS_FAILED
        inst.schedule.save(update_fields=["status"])
    return 1


def _orphan_vast_id(vinst: dict) -> str | None:
    """Return the vast id to destroy if ``vinst`` is an orphan, else None.

    Orphan = a live vast instance whose label is ``wl-sched-<id>`` but
    whose matching AnalysisInstance is terminal or absent (covers a lost
    create-time DB write).
    """
    label = vinst.get("label") or ""
    if not label.startswith(_LABEL_PREFIX):
        return None
    try:
        sched_id = int(label[len(_LABEL_PREFIX):])
    except ValueError:
        return None
    # vast ids are ints; AnalysisInstance.vast_instance_id stores the
    # str() form (see vast_dispatch.create_instance) — stringify to match.
    rec = (
        AnalysisInstance.objects
        .filter(schedule_id=sched_id,
                vast_instance_id=str(vinst.get("id")))
        .first()
    )
    if rec is None or not rec.is_live:
        return str(vinst.get("id"))
    return None


def _reap_orphans(api_key: str) -> int:
    """Destroy any orphaned live vast instances. Return count destroyed."""
    destroyed = 0
    for vinst in vast_dispatch.list_instances(api_key=api_key):
        vid = _orphan_vast_id(vinst)
        if vid is None:
            continue
        if vast_dispatch.destroy_instance(
                api_key=api_key, vast_instance_id=vid)["ok"]:
            destroyed += 1
    return destroyed


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
        destroyed += _reap_one(inst, api_key, now, stale_cutoff)
    _recover_schedules()
    destroyed += _reap_orphans(api_key)
    return destroyed


def _launch(api_key: str) -> int:
    """Launch one instance if scheduled and none live. Implemented in Task 7.

    Returns:
        int: 1 if an instance was launched, else 0.
    """
    return 0
