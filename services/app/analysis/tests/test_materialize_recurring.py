"""
Title: test_materialize_recurring.py — Step 0 of reconcile cron
Description:
    due→1 pending+stamp; not-due→none; disabled→skip; runner-down-
    across-N-occurrences→exactly one; failed prior run does NOT re-fire
    (Option A); bad crontab on one rule doesn't break others; Step 0
    runs before reap/launch.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from analysis.models import (
    AnalysisSchedule, RecurringAnalysisSchedule,
)
from analysis.management.commands.reconcile_vast_analysis import (
    _materialize_recurring,
)


@override_settings(VAST_MAX_JOBS=100)
class MaterializeRecurringTests(TestCase):
    """Step 0 turns due rules into exactly one pending schedule."""

    def test_due_rule_materializes_one_and_stamps(self):
        """A rule with no last_materialized_at and a past fire → 1 row."""
        r = RecurringAnalysisSchedule.objects.create(
            name="every-min", crontab="* * * * *", timezone="UTC")
        n = _materialize_recurring()
        self.assertEqual(n, 1)
        r.refresh_from_db()
        self.assertIsNotNone(r.last_materialized_at)
        sched = AnalysisSchedule.objects.get()
        self.assertEqual(sched.status, AnalysisSchedule.STATUS_PENDING)
        self.assertEqual(sched.recurring_rule_id, r.id)

    def test_not_due_does_nothing(self):
        """last_materialized_at after the last fire → no new row."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", timezone="UTC")
        r.last_materialized_at = timezone.now() + timedelta(days=400)
        r.save(update_fields=["last_materialized_at"])
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 0)

    def test_disabled_rule_skipped(self):
        """A disabled rule never materializes or stamps."""
        RecurringAnalysisSchedule.objects.create(
            name="x", crontab="* * * * *", timezone="UTC", enabled=False)
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 0)

    def test_coalesced_catch_up_one_run(self):
        """Runner down across many occurrences → exactly one make-up."""
        r = RecurringAnalysisSchedule.objects.create(
            name="hourly", crontab="0 * * * *", timezone="UTC")
        r.last_materialized_at = timezone.now() - timedelta(days=5)
        r.save(update_fields=["last_materialized_at"])
        self.assertEqual(_materialize_recurring(), 1)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)
        # A second immediate tick must NOT add another (already stamped).
        self.assertEqual(_materialize_recurring(), 0)

    def test_failed_prior_run_does_not_refire(self):
        """A failed materialized run doesn't re-fire (Option A)."""
        RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", timezone="UTC")
        _materialize_recurring()
        AnalysisSchedule.objects.update(
            status=AnalysisSchedule.STATUS_FAILED)
        self.assertEqual(_materialize_recurring(), 0)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)

    def test_bad_crontab_isolated(self):
        """One un-parseable rule does not block a good rule."""
        good = RecurringAnalysisSchedule.objects.create(
            name="good", crontab="* * * * *", timezone="UTC")
        # Force a stored-but-invalid crontab past clean() via update().
        bad = RecurringAnalysisSchedule.objects.create(
            name="bad", crontab="* * * * *", timezone="UTC")
        RecurringAnalysisSchedule.objects.filter(pk=bad.pk).update(
            crontab="totally-broken")
        n = _materialize_recurring()
        self.assertEqual(n, 1)
        self.assertEqual(
            AnalysisSchedule.objects.filter(
                recurring_rule_id=good.id).count(), 1)

    def test_db_error_on_one_rule_isolated(self):
        """A create() failure on one rule must not abort the others."""
        RecurringAnalysisSchedule.objects.create(
            name="bad-db", crontab="* * * * *", timezone="UTC")
        good = RecurringAnalysisSchedule.objects.create(
            name="good", crontab="* * * * *", timezone="UTC")
        real_create = AnalysisSchedule.objects.create
        calls = {"n": 0}

        def flaky_create(*a, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated DB blip")
            return real_create(*a, **kw)

        with patch(
            "analysis.management.commands.reconcile_vast_analysis."
            "AnalysisSchedule.objects.create",
            side_effect=flaky_create,
        ):
            n = _materialize_recurring()
        self.assertEqual(n, 1)
        self.assertEqual(
            AnalysisSchedule.objects.filter(
                recurring_rule_id=good.id).count(), 1)
