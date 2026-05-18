"""
Title: test_scheduling_helpers.py — cron helper + dependency tests
Description:
    Task 1: croniter import-smoke. Task 4 appends next_runs/prev_fire
    tests to this file.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.test import TestCase


class CroniterDependencyTests(TestCase):
    """croniter must be importable and validate expressions."""

    def test_croniter_importable_and_validates(self):
        """croniter is installed and its is_valid API works."""
        from croniter import croniter
        self.assertTrue(croniter.is_valid("0 2 * * 1"))
        self.assertFalse(croniter.is_valid("not a cron"))
