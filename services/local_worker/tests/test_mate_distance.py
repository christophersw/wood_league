"""
Title: test_mate_distance.py — Tests for the mate-distance CPL heuristic
Description:
    Verifies that mate_distance_cpl returns 0 when the mover had no mate
    before the move, applies the lost-mate blunder penalty when the mover
    relinquishes a forced mate, and charges 50 cp per ply taken beyond
    the optimal (before-1) ply count when the mover still has a mate.

Changelog:
    2026-05-09: Initial creation
"""
from local_worker.analysis._mate_distance import (
    MATE_LOST_CPL,
    MATE_PER_EXTRA_PLY,
    mate_distance_cpl,
)


def test_no_mate_before_returns_zero():
    assert mate_distance_cpl(None, None) == 0
    assert mate_distance_cpl(None, 3) == 0
    # Mover being mated before the move (negative plies) is also "no mate for mover"
    assert mate_distance_cpl(-3, -2) == 0
    assert mate_distance_cpl(0, 0) == 0


def test_lost_mate_charges_blunder_penalty():
    # Had mate-in-1 before, no mate after
    assert mate_distance_cpl(1, None) == MATE_LOST_CPL
    # Had mate-in-5 before, now being mated
    assert mate_distance_cpl(5, -7) == MATE_LOST_CPL
    # Had mate-in-3 before, after_mate exactly 0 also counts as lost
    assert mate_distance_cpl(3, 0) == MATE_LOST_CPL


def test_optimal_mate_play_charges_zero():
    # Mate-in-3 before; after the mover's move, mate-in-2 (3-1) is optimal
    assert mate_distance_cpl(3, 2) == 0
    # Mate-in-1 played correctly: after the move there is no longer a mate
    # (the mate has been delivered) — this is handled by checkmate detection,
    # not this helper. The "after" position is checkmate so the engine
    # would not return a forced mate, and the mover already had M_b == 1
    # which yields penalty 0 only when M_a > 0.
    # Mate-in-2 → mate-in-1 played: after_mate = 1, optimal = 1, no penalty
    assert mate_distance_cpl(2, 1) == 0


def test_extra_plies_charge_per_ply_penalty():
    # Mate-in-2 before, mover's move leaves mate-in-2 (no progress, 1 extra ply)
    assert mate_distance_cpl(2, 2) == MATE_PER_EXTRA_PLY
    # Mate-in-3 before, mate-in-5 after: optimal would be 2, extra = 3 plies
    assert mate_distance_cpl(3, 5) == 3 * MATE_PER_EXTRA_PLY
    # Six extra plies should cross the Blunder threshold
    assert mate_distance_cpl(2, 8) == 7 * MATE_PER_EXTRA_PLY  # 350 cp
