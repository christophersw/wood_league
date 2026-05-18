"""
Title: test_reconcile_vast_gating.py — VAST_* settings + command gating
Description:
    Task 1 covers settings defaults. Later tasks add command-gating tests
    to this file (VAST_ENABLED False → no-op).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase, override_settings


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


class ReconcileGatingTests(TestCase):
    """The command is a safe no-op unless VAST_ENABLED is true."""

    @override_settings(VAST_ENABLED=False)
    def test_disabled_is_noop(self):
        """VAST_ENABLED False → logs one line, touches nothing, exits 0."""
        out = StringIO()
        call_command("reconcile_vast_analysis", stdout=out)
        self.assertIn("disabled", out.getvalue().lower())

    @override_settings(VAST_ENABLED=True, VAST_API_KEY="")
    def test_enabled_without_key_is_noop(self):
        """Missing VAST_API_KEY → no-op (validate env before launch)."""
        out = StringIO()
        call_command("reconcile_vast_analysis", stdout=out)
        self.assertIn("not configured", out.getvalue().lower())
