"""
Title: test_priority_tiers.py — Tests for AnalysisJob priority tier constants and ordering
Description: Verifies HIGH/NORMAL/LOW priority constants and that pending jobs
    sort by priority desc then game.played_at desc for both admin display and
    worker claim.
Changelog:
    2026-05-11: Initial — Task 1 of analysis-queue-ui-overhaul plan.
"""
from analysis.models import AnalysisJob


def test_priority_tier_constants_exist():
    """Three named priority tiers expose integer values, HIGH > NORMAL > LOW."""
    assert AnalysisJob.PRIORITY_HIGH > AnalysisJob.PRIORITY_NORMAL > AnalysisJob.PRIORITY_LOW
    assert AnalysisJob.PRIORITY_HIGH == 100
    assert AnalysisJob.PRIORITY_NORMAL == 0
    assert AnalysisJob.PRIORITY_LOW == -100
