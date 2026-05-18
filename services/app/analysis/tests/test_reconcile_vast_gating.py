"""
Title: test_reconcile_vast_gating.py — VAST_* settings + command gating
Description:
    Task 1 covers settings defaults. Later tasks add command-gating tests
    to this file (VAST_ENABLED False → no-op).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.conf import settings
from django.test import TestCase


class VastSettingsDefaultsTests(TestCase):
    """VAST_* settings exist with safe defaults."""

    def test_vast_enabled_defaults_false(self):
        """VAST_ENABLED must default False (cost-safe; invisible when off)."""
        self.assertFalse(settings.VAST_ENABLED)

    def test_vast_numeric_defaults(self):
        """Numeric/string guards have the exact spec defaults."""
        self.assertEqual(settings.VAST_MAX_JOBS, 100)
        self.assertEqual(settings.VAST_HARD_DEADLINE_HOURS, 6.0)
        self.assertEqual(settings.VAST_LAUNCH_GRACE_MINUTES, 20)
        self.assertEqual(settings.VAST_WORKER_STALE_MINUTES, 15)
        self.assertEqual(settings.VAST_OFFER_GPU_NAME, "L40S")
        self.assertEqual(settings.VAST_OFFER_MAX_DPH, 1.50)
