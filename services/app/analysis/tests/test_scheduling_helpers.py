"""
Title: test_scheduling_helpers.py — cron helper + dependency tests
Description:
    Task 1: croniter import-smoke. Task 4 appends next_runs/prev_fire
    tests to this file.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import TestCase

from analysis import scheduling


class CroniterDependencyTests(TestCase):
    """croniter must be importable and validate expressions."""

    def test_croniter_importable_and_validates(self):
        """croniter is installed and its is_valid API works."""
        from croniter import croniter
        self.assertTrue(croniter.is_valid("0 2 * * 1"))
        self.assertFalse(croniter.is_valid("not a cron"))


class NextRunsTests(TestCase):
    """next_runs returns upcoming fire times in the rule's tz."""

    def test_next_runs_weekly(self):
        """Weekly Monday 02:00 UTC yields Mondays at 02:00."""
        after = datetime(2026, 5, 18, 12, 0, tzinfo=ZoneInfo("UTC"))
        runs = scheduling.next_runs("0 2 * * 1", "UTC", 3, after=after)
        self.assertEqual(len(runs), 3)
        for dt in runs:
            self.assertEqual(dt.weekday(), 0)   # Monday
            self.assertEqual((dt.hour, dt.minute), (2, 0))
        self.assertTrue(runs[0] < runs[1] < runs[2])

    def test_next_runs_respects_timezone(self):
        """A non-UTC tz shifts the wall-clock fire time."""
        after = datetime(2026, 5, 18, 0, 0, tzinfo=ZoneInfo("UTC"))
        runs = scheduling.next_runs(
            "0 9 * * *", "America/New_York", 1, after=after)
        # 09:00 New York == 13:00 or 14:00 UTC depending on DST.
        self.assertIn(runs[0].astimezone(ZoneInfo("UTC")).hour, (13, 14))

    def test_next_runs_invalid_raises(self):
        """An invalid expression raises ValueError."""
        with self.assertRaises(ValueError):
            scheduling.next_runs("bogus", "UTC", 1)

    def test_prev_fire_before_now(self):
        """prev_fire returns the most recent fire <= the given instant."""
        now = datetime(2026, 5, 20, 3, 0, tzinfo=ZoneInfo("UTC"))  # Wed
        prev = scheduling.prev_fire("0 2 * * 1", "UTC", now)  # Mon 02:00
        self.assertEqual(prev.weekday(), 0)
        self.assertTrue(prev <= now)
        self.assertEqual((prev.hour, prev.minute), (2, 0))
