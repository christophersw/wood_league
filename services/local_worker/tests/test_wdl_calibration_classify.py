"""
Title: test_wdl_calibration_classify.py
Description:
    Tests for the draw-aware 2-axis move classifier (classify_draw_aware).
    Verifies base ladder boundaries, modifier strict gates, and counter buckets.
Changelog:
    2026-05-19: Initial creation (issue #159, Task A4).
"""
from local_worker.analysis.wdl_calibration import classify_draw_aware


def test_base_ladder_boundaries():
    assert classify_draw_aware(0.005, 0.0).base == "Best"
    assert classify_draw_aware(0.01, 0.0).base == "Best"
    assert classify_draw_aware(0.02, 0.0).base == "Excellent"
    assert classify_draw_aware(0.05, 0.0).base == "Good"
    assert classify_draw_aware(0.10, 0.0).base == "Inaccuracy"
    assert classify_draw_aware(0.20, 0.0).base == "Mistake"
    assert classify_draw_aware(0.2001, 0.0).base == "Blunder"


def test_modifiers_strict_gates():
    assert classify_draw_aware(0.15, 0.25).modifier == "Missed Win"
    assert classify_draw_aware(0.25, -0.10).modifier == "Losing Blunder"
    assert classify_draw_aware(0.03, -0.25).modifier == "Risky"
    assert classify_draw_aware(0.03, 0.25).modifier == "Simplification"
    assert classify_draw_aware(0.03, 0.0).modifier is None
    assert classify_draw_aware(0.10, 0.20).modifier is None


def test_counter_bucket():
    assert classify_draw_aware(0.0, 0.0).counter_bucket is None
    assert classify_draw_aware(0.08, 0.0).counter_bucket == "inaccuracies"
    assert classify_draw_aware(0.15, 0.0).counter_bucket == "mistakes"
    assert classify_draw_aware(0.30, 0.0).counter_bucket == "blunders"
