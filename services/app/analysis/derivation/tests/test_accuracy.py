"""
Title: test_accuracy.py — Lichess win%-curve + game-accuracy aggregation
Description:
    Issue #161 Phase C. ``derivation.accuracy`` is the single home for
    win-percentage and per-move/game-accuracy math previously scattered across
    worker Stockfish and lc0 paths. These tests pin the canonical numbers from
    ``analysis-math.md`` and the Lichess windowing/harmonic-mean scheme.

Changelog:
    2026-05-19 (#161/C): Initial — adapted from local_worker/tests/test_math.py.
"""
from __future__ import annotations

import math

import pytest

from analysis.derivation.accuracy import (
    game_accuracy,
    lichess_window_size,
    move_accuracy,
    win_pct,
)


class TestWinPct:
    """Sigmoid Win% from a centipawn evaluation."""

    def test_zero_is_fifty(self) -> None:
        """A balanced position scores exactly 50%."""
        assert win_pct(0) == pytest.approx(50.0, abs=1e-9)

    def test_positive_above_fifty(self) -> None:
        """Positive cp favours the mover (Win% > 50)."""
        assert 50.0 < win_pct(100) < 100.0

    def test_negative_below_fifty(self) -> None:
        """Negative cp favours the opponent (Win% < 50)."""
        assert 0.0 < win_pct(-100) < 50.0

    def test_symmetry(self) -> None:
        """Win%(+x) + Win%(-x) = 100 by sigmoid symmetry."""
        assert win_pct(200) + win_pct(-200) == pytest.approx(100.0, abs=1e-9)

    def test_saturation(self) -> None:
        """Mate-magnitude cp values saturate near 0% / 100%."""
        assert win_pct(10000) > 99.9
        assert win_pct(-10000) < 0.1

    def test_canonical_value(self) -> None:
        """Lichess sigmoid coefficient is pinned (analysis-math.md)."""
        expected = 100.0 / (1.0 + math.exp(-0.00368208 * 300))
        assert win_pct(300) == pytest.approx(expected, abs=1e-9)


class TestMoveAccuracy:
    """Per-move accuracy from the mover's Win% drop."""

    def test_no_drop_is_perfect(self) -> None:
        """No Win% drop yields the formula's maximum (≈100; clamped just below)."""
        # 103.1668 - 3.1669 ≈ 99.9999 — within 1e-3 of the clamp ceiling.
        assert move_accuracy(80.0, 80.0) == pytest.approx(100.0, abs=1e-3)

    def test_clamped_to_floor(self) -> None:
        """A catastrophic drop is clamped at 0, not negative."""
        assert move_accuracy(95.0, 5.0) >= 0.0

    def test_monotone_decreasing(self) -> None:
        """Larger drops never produce higher accuracy."""
        a = move_accuracy(80.0, 70.0)
        b = move_accuracy(80.0, 40.0)
        assert a > b


class TestWindowSize:
    """Lichess window-size formula: k = clamp(num_plies // 10, 2, 8)."""

    @pytest.mark.parametrize("n,k", [(0, 2), (15, 2), (50, 5), (90, 8), (200, 8)])
    def test_clamped_range(self, n: int, k: int) -> None:
        """Window size clamps to [2, 8] across the full input range."""
        assert lichess_window_size(n) == k


class TestGameAccuracy:
    """Volatility-weighted + harmonic mean aggregation."""

    def test_empty_input_returns_zero(self) -> None:
        """A side with no moves scores 0.0."""
        assert game_accuracy([], all_win_pcts=[50.0], mover_ply_indices=[]) == 0.0

    def test_all_perfect_moves_returns_about_100(self) -> None:
        """A side that played all-perfect moves on a flat game scores ~100."""
        # 6-ply game, win% always 50 → zero volatility → harmonic mean dominates.
        all_wp = [50.0] * 7
        white_idx = [1, 3, 5]
        result = game_accuracy(
            [100.0, 100.0, 100.0], all_win_pcts=all_wp, mover_ply_indices=white_idx,
        )
        assert result == pytest.approx(100.0, abs=1e-6)

    def test_mismatched_lengths_raise(self) -> None:
        """Per-move accuracies and mover-ply indices must have equal length."""
        with pytest.raises(ValueError):
            game_accuracy(
                [100.0, 90.0],
                all_win_pcts=[50.0, 50.0, 50.0],
                mover_ply_indices=[1],
            )

    def test_returns_clamped_to_unit_interval_scaled_by_100(self) -> None:
        """Result always lies in [0, 100]."""
        all_wp = [50.0, 90.0, 10.0, 80.0, 20.0, 70.0, 30.0]
        white_idx = [1, 3, 5]
        # Realistic accuracies for a noisy game.
        result = game_accuracy(
            [85.0, 60.0, 40.0], all_win_pcts=all_wp, mover_ply_indices=white_idx,
        )
        assert 0.0 <= result <= 100.0
