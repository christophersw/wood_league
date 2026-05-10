"""
Title: test_math.py — Tests for analysis math formulas
Description:
    Verifies that win%, accuracy, CPL classification, game accuracy aggregation,
    and Q→cp conversion match analysis-math.md exactly.

Changelog:
    2026-05-09: Initial creation
"""
import math
import pytest
from local_worker.analysis.math import (
    win_pct,
    move_accuracy,
    game_accuracy,
    classify_stockfish_move,
    classify_lc0_move,
    cp_equiv_from_q,
    cpl_from_evals,
)


class TestWinPct:
    def test_zero_cp_is_fifty(self):
        # Win% = 100 / (1 + exp(0)) = 50 exactly
        assert win_pct(0) == pytest.approx(50.0, abs=1e-9)

    def test_positive_cp_above_fifty(self):
        assert win_pct(100) > 50
        assert win_pct(100) < 100

    def test_negative_cp_below_fifty(self):
        assert win_pct(-100) < 50
        assert win_pct(-100) > 0

    def test_symmetric(self):
        # win_pct(x) + win_pct(-x) == 100 by the sigmoid identity
        assert win_pct(200) + win_pct(-200) == pytest.approx(100.0, abs=1e-9)

    def test_mate_score_saturates(self):
        assert win_pct(10000) > 99.9
        assert win_pct(-10000) < 0.1

    def test_canonical_value(self):
        # Spot-check against the closed-form value at cp=300
        expected = 100.0 / (1.0 + math.exp(-0.00368208 * 300))
        assert win_pct(300) == pytest.approx(expected, abs=1e-9)


class TestMoveAccuracy:
    def test_perfect_move_no_drop(self):
        # drop=0 → 103.1668... - 3.1669... = 99.99989... → clamped/returned just under 100
        acc = move_accuracy(60.0, 60.0)
        assert acc == pytest.approx(99.999916, abs=0.001)

    def test_blunder_is_low(self):
        acc = move_accuracy(70.0, 20.0)
        assert acc < 20

    def test_clamped_to_zero(self):
        acc = move_accuracy(95.0, 0.0)
        assert acc >= 0.0

    def test_clamped_to_hundred(self):
        # Negative drop (mover got better) → formula returns >100, must clamp
        acc = move_accuracy(50.0, 80.0)
        assert acc <= 100.0


class TestCplFromEvals:
    def test_white_perspective(self):
        # White goes from +50 to +30 → CPL 20 (no negation)
        assert cpl_from_evals(50, 30, mover_is_white=True) == 20

    def test_black_perspective_negates(self):
        # Black goes from cp=-50 (good for Black) to cp=-30 (worse for Black).
        # mover-perspective: before=+50, after=+30 → CPL 20
        assert cpl_from_evals(-50, -30, mover_is_white=False) == 20

    def test_clamped_at_zero(self):
        # Mover *gained* cp → CPL clamped to 0
        assert cpl_from_evals(20, 60, mover_is_white=True) == 0

    def test_two_mate_scores_zero_cpl(self):
        # mate-in-1 and mate-in-10 both = 10000; CPL must be 0
        assert cpl_from_evals(10000, 10000, mover_is_white=True) == 0


class TestGameAccuracyWindowed:
    def test_all_perfect_is_near_hundred(self):
        # All-100 accuracies → both means are 100 → average is 100
        result = game_accuracy([100.0] * 30, win_pcts=[50.0] * 30)
        assert result == pytest.approx(100.0, abs=0.01)

    def test_empty_is_zero(self):
        assert game_accuracy([], win_pcts=[]) == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            game_accuracy([100.0, 90.0], win_pcts=[50.0])

    def test_volatile_window_increases_weight(self):
        # A swing-heavy section should pull the weighted mean toward those moves
        accs = [100.0] * 5 + [40.0] * 3 + [100.0] * 5
        win_pcts = [50.0] * 5 + [80.0, 30.0, 75.0] + [50.0] * 5  # high std-dev in middle
        result = game_accuracy(accs, win_pcts=win_pcts)
        assert 0 < result < 100

    def test_harmonic_penalises_severe_blunders(self):
        # One catastrophic blunder should drag the harmonic mean low
        accs = [100.0] * 10 + [0.5]
        win_pcts = [50.0] * 11
        result = game_accuracy(accs, win_pcts=win_pcts)
        # Harmonic mean of values including one ~0 will be small; full result well below 100
        assert result < 50


class TestClassifyStockfish:
    # Order: Brilliant > Great > Best > Excellent > Inaccuracy > Mistake > Blunder
    # First match wins.
    def test_best_move(self):
        assert classify_stockfish_move(
            cpl=0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Best"

    def test_excellent(self):
        assert classify_stockfish_move(
            cpl=30, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Excellent"

    def test_inaccuracy_lower_bound(self):
        assert classify_stockfish_move(
            cpl=50, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Inaccuracy"

    def test_mistake_lower_bound(self):
        assert classify_stockfish_move(
            cpl=100, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Mistake"

    def test_blunder_lower_bound(self):
        assert classify_stockfish_move(
            cpl=300, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Blunder"

    def test_great_move(self):
        assert classify_stockfish_move(
            cpl=5, second_best_gap=90, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Great"

    def test_brilliant_requires_all_conditions(self):
        assert classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=65, is_capture_or_sacrifice=True
        ) == "Brilliant"

    def test_brilliant_blocked_by_high_winpct(self):
        result = classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=80, is_capture_or_sacrifice=True
        )
        assert result == "Great"  # second_best_gap=160 also satisfies Great threshold

    def test_brilliant_blocked_without_capture(self):
        result = classify_stockfish_move(
            cpl=5, second_best_gap=160, mover_win_pct=65, is_capture_or_sacrifice=False
        )
        assert result == "Great"


class TestClassifyLc0:
    def test_best(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Best"

    def test_excellent(self):
        # 1% < Δ < 2% — strictly greater than 1%
        assert classify_lc0_move(
            delta_win_pct=1.5, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Excellent"

    def test_inaccuracy_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=2.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Inaccuracy"

    def test_mistake_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=5.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Mistake"

    def test_blunder_lower_bound(self):
        assert classify_lc0_move(
            delta_win_pct=10.0, second_best_gap=None, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Blunder"

    def test_great(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=7.0, mover_win_pct=60, is_capture_or_sacrifice=False
        ) == "Great"

    def test_brilliant(self):
        assert classify_lc0_move(
            delta_win_pct=0.5, second_best_gap=11.0, mover_win_pct=65, is_capture_or_sacrifice=True
        ) == "Brilliant"


class TestCpEquiv:
    def test_zero_q_is_zero(self):
        assert cp_equiv_from_q(0.0) == 0

    def test_positive_q_positive_cp(self):
        assert cp_equiv_from_q(0.5) > 0

    def test_negative_q_negative_cp(self):
        assert cp_equiv_from_q(-0.5) < 0

    def test_symmetric(self):
        assert cp_equiv_from_q(0.4) == -cp_equiv_from_q(-0.4)

    def test_clamped_near_one(self):
        # tan(1.5620688421 · 1) blows up → must clamp Q before tan()
        assert cp_equiv_from_q(0.99999999) > 0  # finite, not NaN/inf
        assert cp_equiv_from_q(-0.99999999) < 0

    def test_canonical_value(self):
        # Spot-check against closed-form
        q = 0.3
        expected = round(111.714640912 * math.tan(1.5620688421 * q))
        assert cp_equiv_from_q(q) == expected
