"""
Title: test_recurring_form.py — RecurringAnalysisScheduleForm
Description:
    Valid input saves; invalid crontab and invalid timezone are
    rejected with field errors (mirrors model clean()).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.test import TestCase

from analysis.forms import RecurringAnalysisScheduleForm


class RecurringFormTests(TestCase):
    """Form validation mirrors model clean()."""

    def test_valid_form_saves(self):
        """A valid crontab + tz produces a saved rule."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "Weekly Mon 02:00", "crontab": "0 2 * * 1",
            "timezone": "UTC", "max_jobs": "", "note": ""})
        self.assertTrue(form.is_valid(), form.errors.as_json())
        obj = form.save()
        self.assertEqual(obj.crontab, "0 2 * * 1")

    def test_invalid_crontab_rejected(self):
        """A bad crontab yields a crontab field error."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "x", "crontab": "nope", "timezone": "UTC"})
        self.assertFalse(form.is_valid())
        self.assertIn("crontab", form.errors)

    def test_invalid_timezone_rejected(self):
        """A bad timezone yields a timezone field error."""
        form = RecurringAnalysisScheduleForm(data={
            "name": "x", "crontab": "0 2 * * 1",
            "timezone": "Nowhere/Land"})
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)
