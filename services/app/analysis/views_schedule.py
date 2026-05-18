"""
Title: views_schedule.py — admin scheduling page (issue #155 B)
Description:
    _admin_login_required page to manage RecurringAnalysisSchedule
    rules and one-off runs, plus "recent runs" / "future planned runs"
    tables and an HTMX cron preview. Produces pending AnalysisSchedule
    rows that Sub-project A's reconcile cron consumes.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.db.models import OuterRef, Subquery
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import scheduling
from .forms import RecurringAnalysisScheduleForm
from .models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
)
from .views import _admin_login_required

_PREVIEW_COUNT = 3


def _future_rows() -> list[dict]:
    """Next occurrence per enabled rule + non-terminal one-offs."""
    rows: list[dict] = []
    for rule in RecurringAnalysisSchedule.objects.filter(enabled=True):
        try:
            nxt = scheduling.next_runs(rule.crontab, rule.timezone, 1)[0]
        except (ValueError, KeyError):
            continue
        rows.append({"when": nxt, "source": rule.name,
                     "max_jobs": rule.effective_max_jobs(),
                     "status": "scheduled"})
    pend = AnalysisSchedule.objects.filter(
        status__in=[AnalysisSchedule.STATUS_PENDING,
                    AnalysisSchedule.STATUS_RUNNING]
    ).select_related("recurring_rule")
    for s in pend:
        rows.append({
            "when": s.created_at,
            "source": s.recurring_rule.name if s.recurring_rule
            else "one-off",
            "max_jobs": s.max_jobs, "status": s.status})
    return rows


def _recent_rows(limit: int = 50) -> list[dict]:
    """Terminal schedules + their latest instance (single query).

    Uses a correlated Subquery to fetch each schedule's most-recent
    AnalysisInstance fields, avoiding an N+1 over the result set.
    """
    latest = (AnalysisInstance.objects
              .filter(schedule=OuterRef("pk"))
              .order_by("-created_at"))
    qs = (AnalysisSchedule.objects
          .filter(status__in=[AnalysisSchedule.STATUS_DONE,
                              AnalysisSchedule.STATUS_FAILED])
          .select_related("recurring_rule")
          .annotate(
              latest_vast_id=Subquery(
                  latest.values("vast_instance_id")[:1]),
              latest_dph=Subquery(latest.values("offer_dph")[:1]),
          )
          .order_by("-created_at")[:limit])
    return [
        {
            "id": s.id,
            "when": s.created_at,
            "source": (s.recurring_rule.name if s.recurring_rule
                       else "one-off"),
            "status": s.status,
            "failed": s.status == AnalysisSchedule.STATUS_FAILED,
            "instance_id": s.latest_vast_id,
            "offer_dph": s.latest_dph,
        }
        for s in qs
    ]


def _render_page(request: HttpRequest,
                 form: RecurringAnalysisScheduleForm,
                 status: int = 200) -> HttpResponse:
    """Render the scheduling page with all sections."""
    ctx = {
        "form": form,
        "rules": RecurringAnalysisSchedule.objects.all(),
        "future_rows": _future_rows(),
        "recent_rows": _recent_rows(),
    }
    return render(request, "analysis/scheduling.html", ctx, status=status)


@_admin_login_required
@require_GET
def scheduling_page(request: HttpRequest) -> HttpResponse:
    """Render the scheduling admin page."""
    return _render_page(request, RecurringAnalysisScheduleForm())


@_admin_login_required
@require_POST
def rule_create(request: HttpRequest) -> HttpResponse:
    """Create a recurring rule, or re-render with errors."""
    form = RecurringAnalysisScheduleForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect("analysis:scheduling")
    return _render_page(request, form, status=200)


@_admin_login_required
@require_POST
def rule_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """Edit an existing rule, or re-render with errors."""
    rule = get_object_or_404(RecurringAnalysisSchedule, pk=pk)
    form = RecurringAnalysisScheduleForm(request.POST, instance=rule)
    if form.is_valid():
        form.save()
        return redirect("analysis:scheduling")
    return _render_page(request, form, status=200)


@_admin_login_required
@require_POST
def rule_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """Delete a rule (history rows keep, FK SET_NULL)."""
    get_object_or_404(RecurringAnalysisSchedule, pk=pk).delete()
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def rule_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """Flip a rule's enabled flag."""
    rule = get_object_or_404(RecurringAnalysisSchedule, pk=pk)
    rule.enabled = not rule.enabled
    rule.save(update_fields=["enabled", "updated_at"])
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def run_once(request: HttpRequest) -> HttpResponse:
    """Create a one-off pending schedule (next-tick launch)."""
    AnalysisSchedule.objects.create(
        status=AnalysisSchedule.STATUS_PENDING)
    return redirect("analysis:scheduling")


@_admin_login_required
@require_POST
def rerun(request: HttpRequest, pk: int) -> HttpResponse:
    """Create a fresh one-off copying the source's max_jobs."""
    src = get_object_or_404(AnalysisSchedule, pk=pk)
    AnalysisSchedule.objects.create(
        status=AnalysisSchedule.STATUS_PENDING, max_jobs=src.max_jobs)
    return redirect("analysis:scheduling")


@_admin_login_required
@require_GET
def schedule_preview(request: HttpRequest) -> HttpResponse:
    """HTMX partial: next runs for a candidate crontab, or an error."""
    crontab = request.GET.get("crontab", "")
    tz = request.GET.get("timezone", "UTC")
    error = None
    runs: list = []
    try:
        runs = scheduling.next_runs(crontab, tz, _PREVIEW_COUNT)
    except ValueError:
        error = "Invalid cron expression or timezone."
    return render(request, "analysis/_schedule_preview.html",
                  {"runs": runs, "error": error})
