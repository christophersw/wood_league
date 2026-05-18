"""
Title: test_admin_recurring.py — admin registration for the rule model
Description:
    RecurringAnalysisSchedule must be registered (operator fallback).
Changelog:
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from django.contrib import admin
from django.test import TestCase

from analysis.models import RecurringAnalysisSchedule


class RecurringAdminTests(TestCase):
    """The rule model is registered in Django admin."""

    def test_registered(self):
        """RecurringAnalysisSchedule appears in the admin registry."""
        self.assertTrue(
            admin.site.is_registered(RecurringAnalysisSchedule))
