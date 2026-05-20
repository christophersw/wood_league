"""
Title: test_lc0_models_fields.py — Structural contract tests for Lc0 dataclasses
Description:
    Verifies that Lc0MoveResult and Lc0GameResult expose exactly the fields
    introduced in issue #159 Phase C1 (raw + rescaled WDL, draw-aware class,
    calibration provenance). These are pure dataclass structure checks —
    no engine required.

Changelog:
    2026-05-19: Initial creation (issue #159 Phase C1)
"""
from __future__ import annotations

import dataclasses

from local_worker.analysis.models import Lc0MoveResult, Lc0GameResult


def test_move_result_has_raw_and_rescaled_fields():
    """Lc0MoveResult must expose both raw and rescaled WDL triplets plus deltas."""
    field_names = {f.name for f in dataclasses.fields(Lc0MoveResult)}
    # Raw network output
    assert "wdl_win" in field_names
    assert "wdl_draw" in field_names
    assert "wdl_loss" in field_names
    # Rescaled output
    assert "wdl_win_adj" in field_names
    assert "wdl_draw_adj" in field_names
    assert "wdl_loss_adj" in field_names
    # Mu and deltas
    assert "wdl_mu" in field_names
    assert "delta_mu" in field_names
    assert "delta_d" in field_names
    # Draw-aware classification
    assert "base_severity" in field_names
    assert "draw_character" in field_names
    # Renamed: old 'classification' field must NOT exist
    assert "classification" not in field_names


def test_game_result_keeps_counter_fields():
    """Lc0GameResult must retain blunder/mistake/inaccuracy counters and add calibration fields."""
    field_names = {f.name for f in dataclasses.fields(Lc0GameResult)}
    # Existing counter fields still present
    assert "white_blunders" in field_names
    assert "white_mistakes" in field_names
    assert "white_inaccuracies" in field_names
    assert "black_blunders" in field_names
    assert "black_mistakes" in field_names
    assert "black_inaccuracies" in field_names
    # New calibration provenance fields
    assert "draw_rate_reference" in field_names
    assert "wdl_calibration_elo" in field_names
    assert "contempt" in field_names
