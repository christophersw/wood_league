"""
Title: test_views_schedule.py — scheduling page + actions
Description:
    _admin_login_required gating; rule CRUD/toggle; run-once; re-run;
    tables render; HTMX preview ok + error.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

import uuid

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from analysis.models import (
    AnalysisInstance, AnalysisSchedule, RecurringAnalysisSchedule,
)


def _user(role: str) -> User:
    return User.objects.create_user(
        email=f"{role}-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only
        role=role)


class SchedulingGatingTests(TestCase):
    """_admin_login_required protects every scheduling endpoint."""

    def test_anonymous_redirected(self):
        """Anonymous GET → login redirect (302)."""
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertEqual(resp.status_code, 302)

    def test_non_admin_forbidden(self):
        """Authenticated non-admin → not 200 (403/redirect)."""
        self.client.force_login(_user("player"))
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertNotEqual(resp.status_code, 200)

    def test_admin_ok(self):
        """Admin GET → 200 and the page renders."""
        self.client.force_login(_user("admin"))
        resp = self.client.get(reverse("analysis:scheduling"))
        self.assertEqual(resp.status_code, 200)


class SchedulingActionsTests(TestCase):
    """CRUD, run-once, re-run, preview."""

    def setUp(self):
        self.client.force_login(_user("admin"))

    def test_rule_create_valid(self):
        """Posting a valid rule creates it and redirects."""
        resp = self.client.post(reverse("analysis:rule_create"), {
            "name": "wk", "crontab": "0 2 * * 1", "timezone": "UTC",
            "max_jobs": "", "note": "", "enabled": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 1)

    def test_rule_create_invalid_crontab_no_save(self):
        """An invalid crontab does not create a rule (page re-renders)."""
        resp = self.client.post(reverse("analysis:rule_create"), {
            "name": "x", "crontab": "bad", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 0)

    def test_rule_toggle(self):
        """Toggle flips enabled."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.client.post(reverse("analysis:rule_toggle", args=[r.pk]))
        r.refresh_from_db()
        self.assertFalse(r.enabled)

    def test_rule_delete(self):
        """Delete removes the rule."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.client.post(reverse("analysis:rule_delete", args=[r.pk]))
        self.assertEqual(RecurringAnalysisSchedule.objects.count(), 0)

    def test_run_once_creates_pending(self):
        """Run-once creates a one-off pending schedule (no rule)."""
        resp = self.client.post(reverse("analysis:run_once"), follow=True)
        s = AnalysisSchedule.objects.get()
        self.assertEqual(s.status, AnalysisSchedule.STATUS_PENDING)
        self.assertIsNone(s.recurring_rule)
        self.assertIsNone(s.max_jobs)
        msgs = [str(m) for m in resp.context["messages"]]
        self.assertTrue(
            any(f"Run #{s.pk} queued" in m for m in msgs),
            f"expected success flash, got {msgs!r}")

    def test_run_once_accepts_max_jobs(self):
        """A positive ``max_jobs`` POST value is stored on the row."""
        resp = self.client.post(
            reverse("analysis:run_once"),
            data={"max_jobs": "42"}, follow=True)
        s = AnalysisSchedule.objects.get()
        self.assertEqual(s.max_jobs, 42)
        msgs = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("max_jobs=42" in m for m in msgs))

    def test_run_once_ignores_blank_and_bad_max_jobs(self):
        """Blank, zero, negative, or non-integer ``max_jobs`` → None."""
        for raw in ("", "0", "-3", "abc"):
            AnalysisSchedule.objects.all().delete()
            self.client.post(
                reverse("analysis:run_once"), data={"max_jobs": raw})
            self.assertIsNone(
                AnalysisSchedule.objects.get().max_jobs,
                f"raw={raw!r} should fall through to None")

    def test_rerun_creates_new_pending(self):
        """Re-run creates a fresh pending one-off copying max_jobs."""
        src = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_FAILED, max_jobs=55)
        resp = self.client.post(
            reverse("analysis:rerun", args=[src.pk]), follow=True)
        new = AnalysisSchedule.objects.exclude(pk=src.pk).get()
        self.assertEqual(new.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(new.max_jobs, 55)
        msgs = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any(
            f"Re-run #{new.pk} queued from #{src.pk}" in m for m in msgs))

    def test_recent_and_future_tables_render(self):
        """A terminal run shows in recent; an enabled rule in future."""
        RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        sched = AnalysisSchedule.objects.create(
            status=AnalysisSchedule.STATUS_DONE)
        AnalysisInstance.objects.create(
            schedule=sched, status=AnalysisInstance.STATUS_DESTROYED,
            vast_instance_id="42", offer_dph=0.9)
        body = self.client.get(
            reverse("analysis:scheduling")).content.decode()
        self.assertIn("wk", body)
        self.assertIn("42", body)

    def test_rule_edit_updates(self):
        """Posting to rule_edit changes the rule's crontab."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", timezone="UTC")
        resp = self.client.post(
            reverse("analysis:rule_edit", args=[r.pk]),
            {"name": "wk", "crontab": "0 5 * * 3",
             "timezone": "UTC", "max_jobs": "", "enabled": "on"})
        self.assertEqual(resp.status_code, 302)
        r.refresh_from_db()
        self.assertEqual(r.crontab, "0 5 * * 3")

    def test_preview_ok(self):
        """Preview returns next runs for a valid expression."""
        resp = self.client.get(reverse("analysis:schedule_preview"), {
            "crontab": "0 2 * * 1", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Invalid", resp.content.decode())

    def test_preview_invalid_graceful(self):
        """Preview shows an error string, not a 500, on bad input."""
        resp = self.client.get(reverse("analysis:schedule_preview"), {
            "crontab": "bogus", "timezone": "UTC"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Invalid", resp.content.decode())
