"""
Title: test_models_recurring.py — RecurringAnalysisSchedule model
Description:
    crontab/timezone validation via clean(), max_jobs fallback,
    recurring_rule FK SET_NULL on rule delete.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from analysis.models import (
    AnalysisSchedule, RecurringAnalysisSchedule,
)


class RecurringModelTests(TestCase):
    """Validation, defaults, and FK behaviour."""

    def test_defaults(self):
        """A new rule is enabled with no last_materialized_at."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        self.assertTrue(r.enabled)
        self.assertIsNone(r.last_materialized_at)
        self.assertEqual(r.timezone, "UTC")

    def test_clean_rejects_bad_crontab(self):
        """An invalid crontab fails clean()."""
        r = RecurringAnalysisSchedule(name="x", crontab="nope")
        with self.assertRaises(ValidationError):
            r.full_clean()

    def test_clean_rejects_bad_timezone(self):
        """An unknown timezone fails clean()."""
        r = RecurringAnalysisSchedule(
            name="x", crontab="0 2 * * 1", timezone="Mars/Olympus")
        with self.assertRaises(ValidationError):
            r.full_clean()

    @override_settings(VAST_MAX_JOBS=100)
    def test_effective_max_jobs_fallback(self):
        """Null max_jobs falls back to settings.VAST_MAX_JOBS."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1", max_jobs=None)
        self.assertEqual(r.effective_max_jobs(), 100)
        r2 = RecurringAnalysisSchedule.objects.create(
            name="wk2", crontab="0 2 * * 1", max_jobs=7)
        self.assertEqual(r2.effective_max_jobs(), 7)

    def test_schedule_fk_set_null_on_rule_delete(self):
        """Deleting a rule nulls recurring_rule, keeps the schedule."""
        r = RecurringAnalysisSchedule.objects.create(
            name="wk", crontab="0 2 * * 1")
        s = AnalysisSchedule.objects.create(recurring_rule=r)
        r.delete()
        s.refresh_from_db()
        self.assertIsNone(s.recurring_rule)
        self.assertEqual(AnalysisSchedule.objects.count(), 1)
