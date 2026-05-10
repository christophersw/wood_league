"""
Title: test_math.py — Tests for analysis math formulas
Description:
    Verifies that win%, accuracy, CPL classification, game accuracy aggregation,
    and Q→cp conversion match analysis-math.md exactly.

Changelog:
    2026-05-09: Initial creation
    2026-05-10: Updated game_accuracy tests to use new Lichess-aligned API
                (all_win_pcts + mover_ply_indices). Added front-padding,
                weight-clamp, and hand-computed regression tests.
"""
import math
import statistics
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
from local_worker.analysis._windowing import (
    lichess_window_size,
    compute_ply_weights,
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
    """Tests for game_accuracy() using the new Lichess-aligned API."""

    def _make_game(self, num_white_moves: int, num_black_moves: int):
        """Build trivial all_win_pcts (constant 50%) and ply indices."""
        num_plies = num_white_moves + num_black_moves
        all_wp = [50.0] * (num_plies + 1)
        white_indices = list(range(1, num_plies + 1, 2))[:num_white_moves]
        black_indices = list(range(2, num_plies + 1, 2))[:num_black_moves]
        return all_wp, white_indices, black_indices

    def test_all_perfect_is_near_hundred(self):
        # 30-ply game, White has 15 moves all 100% accuracy → result ~100
        num_plies = 30
        all_wp = [50.0] * (num_plies + 1)
        white_indices = list(range(1, num_plies + 1, 2))
        result = game_accuracy(
            [100.0] * 15,
            all_win_pcts=all_wp,
            mover_ply_indices=white_indices,
        )
        assert result == pytest.approx(100.0, abs=0.01)

    def test_empty_is_zero(self):
        assert game_accuracy([], all_win_pcts=[50.0], mover_ply_indices=[]) == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            game_accuracy(
                [100.0, 90.0],
                all_win_pcts=[50.0, 50.0, 50.0],
                mover_ply_indices=[1],  # length 1 != length 2
            )

    def test_volatile_window_increases_weight(self):
        # A swing-heavy game-wide sequence should affect the weighted mean.
        # 13-ply game; White moves on plies 1,3,5,7,9,11,13.
        # Inject a Win% swing in the middle.
        all_wp = [50.0, 50.0, 50.0, 50.0, 50.0, 80.0, 30.0, 75.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0]
        # accs: first 5 perfect, middle 1 poor, last 1 perfect
        accs = [100.0, 100.0, 100.0, 40.0, 100.0, 100.0, 100.0]
        white_indices = [1, 3, 5, 7, 9, 11, 13]
        result = game_accuracy(accs, all_win_pcts=all_wp, mover_ply_indices=white_indices)
        assert 0 < result < 100

    def test_harmonic_penalises_severe_blunders(self):
        # One catastrophic blunder drags the harmonic mean very low.
        # 22-ply game; White has 11 moves.
        num_plies = 22
        all_wp = [50.0] * (num_plies + 1)
        white_indices = list(range(1, num_plies + 1, 2))
        accs = [100.0] * 10 + [0.5]
        result = game_accuracy(
            accs,
            all_win_pcts=all_wp,
            mover_ply_indices=white_indices,
        )
        assert result < 50

    # --- New required tests ---

    def test_front_padding_short_game(self):
        """Window size = 2 for a < 20-ply game; first k-2 = 0 plies padded.

        With k=2 (for num_plies=6), k-2=0, so there is no front-padding —
        every ply's weight is the stddev of the 2-element window starting at
        max(0, i-1).  We verify that compute_ply_weights returns 6 weights
        (one per ply) and game_accuracy runs without error.
        """
        # 6-ply game: alternating 50 / 80 Win% to give non-trivial stddev.
        all_wp = [50.0, 80.0, 50.0, 80.0, 50.0, 80.0, 50.0]  # length 7
        assert lichess_window_size(6) == 2
        weights = compute_ply_weights(all_wp)
        assert len(weights) == 6
        # Each window is 2 elements; stddev(50, 80) ≈ 15 → clamped to 12.
        for w in weights:
            assert w == pytest.approx(12.0, abs=0.01)

        accs = [70.0, 60.0, 80.0]  # White on plies 1, 3, 5
        result = game_accuracy(
            accs,
            all_win_pcts=all_wp,
            mover_ply_indices=[1, 3, 5],
        )
        assert 0 < result < 100

    def test_front_padding_larger_window(self):
        """With k=4 (40-ply game), first k-2=2 plies share the leading window weight."""
        num_plies = 40
        assert lichess_window_size(num_plies) == 4
        all_wp = [50.0] * (num_plies + 1)
        weights = compute_ply_weights(all_wp)
        assert len(weights) == num_plies
        # All constant → pstdev = 0 → clamped to 0.5
        assert weights[0] == pytest.approx(0.5)
        assert weights[1] == pytest.approx(0.5)

    def test_weight_clamp_floor_constant_game(self):
        """Constant Win% → all stddevs = 0.0 → all weights clamped to 0.5."""
        num_plies = 20
        all_wp = [60.0] * (num_plies + 1)
        weights = compute_ply_weights(all_wp)
        for w in weights:
            assert w == pytest.approx(0.5)

    def test_weight_clamp_ceiling_explosive_swing(self):
        """Single large Win% swing → window stddev > 12 → weight clamped to 12."""
        # alternating 0 / 100 — stddev of any 2-element window = 50 → clamped to 12
        num_plies = 6
        all_wp = [0.0, 100.0, 0.0, 100.0, 0.0, 100.0, 0.0]
        weights = compute_ply_weights(all_wp)
        assert any(w == pytest.approx(12.0) for w in weights)

    def test_regression_hand_computed_6_ply(self):
        """Hand-computed regression for a 6-ply game.

        Setup:
          all_win_pcts = [50, 60, 40, 70, 30, 80, 50]  (length 7)
          num_plies = 6  →  k = clamp(0, 2, 8) = 2
          White moves on plies 1, 3, 5 (indices 1, 3, 5 in all_win_pcts).
          Black moves on plies 2, 4, 6 (indices 2, 4, 6).

        Ply weights (k=2, window start = max(0, i-1)):
          ply 1 (i=1): window all_wp[0:2] = [50,60], pstdev ≈ 5.0  → clamped to 5.0
          ply 2 (i=2): window all_wp[1:3] = [60,40], pstdev = 10.0 → 10.0
          ply 3 (i=3): window all_wp[2:4] = [40,70], pstdev = 15.0 → clamped to 12.0
          ply 4 (i=4): window all_wp[3:5] = [70,30], pstdev = 20.0 → clamped to 12.0
          ply 5 (i=5): window all_wp[4:6] = [30,80], pstdev = 25.0 → clamped to 12.0
          ply 6 (i=6): window all_wp[5:7] = [80,50], pstdev = 15.0 → clamped to 12.0

        White player weights: [5.0, 12.0, 12.0] for plies 1, 3, 5.
        White accuracies: [90, 80, 70]
        weighted_mean_white = (5*90 + 12*80 + 12*70) / (5+12+12)
                            = (450 + 960 + 840) / 29
                            = 2250 / 29
                            ≈ 77.5862...

        harmonic_white = 3 / (1/90 + 1/80 + 1/70)
                       = 3 / (0.011111 + 0.012500 + 0.014286)
                       = 3 / 0.037897
                       ≈ 79.1627...

        game_accuracy_white = (77.5862 + 79.1627) / 2 ≈ 78.3745
        """
        all_wp = [50.0, 60.0, 40.0, 70.0, 30.0, 80.0, 50.0]
        white_accs = [90.0, 80.0, 70.0]
        white_indices = [1, 3, 5]

        # Verify window size
        assert lichess_window_size(6) == 2

        # Hand-compute expected
        w1 = min(12.0, max(0.5, statistics.pstdev([50.0, 60.0])))
        w3 = min(12.0, max(0.5, statistics.pstdev([40.0, 70.0])))
        w5 = min(12.0, max(0.5, statistics.pstdev([30.0, 80.0])))
        weighted_mean = (w1 * 90 + w3 * 80 + w5 * 70) / (w1 + w3 + w5)
        harmonic = 3 / (1 / 90 + 1 / 80 + 1 / 70)
        expected = (weighted_mean + harmonic) / 2.0

        result = game_accuracy(
            white_accs,
            all_win_pcts=all_wp,
            mover_ply_indices=white_indices,
        )
        assert result == pytest.approx(expected, abs=1e-6)


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
