"""
Title: test_admin_vast.py — admin registration for vast scheduling models
Description:
    AnalysisSchedule (operator-insertable trigger) and AnalysisInstance
    (read-mostly live/teardown view) must be registered in Django admin.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from django.contrib import admin
from django.test import TestCase

from analysis.models import AnalysisInstance, AnalysisSchedule


class VastAdminRegistrationTests(TestCase):
    """The two scheduling models are registered in admin."""

    def test_schedule_registered(self):
        """AnalysisSchedule appears in the admin registry."""
        self.assertTrue(admin.site.is_registered(AnalysisSchedule))

    def test_instance_registered(self):
        """AnalysisInstance appears in the admin registry."""
        self.assertTrue(admin.site.is_registered(AnalysisInstance))
