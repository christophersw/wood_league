"""
Title: test_lc0_complete_serializer.py — Tests for Lc0MoveSerializer / Lc0CompleteSerializer
Description:
    TDD tests covering the new WDL-calibration fields added to the Lc0
    serializers in #159 (D2).  Verifies that:
    - New per-move fields (wdl_win_adj, wdl_draw_adj, wdl_loss_adj, wdl_mu,
      delta_mu, delta_d, base_severity, draw_character) are accepted.
    - New per-game fields (draw_rate_reference, wdl_calibration_elo, contempt)
      are accepted.
    - base_severity rejects values not in LC0_SEVERITY_CHOICES.
    - draw_character accepts None (most moves have no draw character).

Changelog:
    2026-05-19 (#159/D2): Initial creation — failing tests before implementation
"""

from api.serializers import Lc0CompleteSerializer

# ---------------------------------------------------------------------------
# Base move payload — every required per-move field
# ---------------------------------------------------------------------------

BASE_MOVE = dict(
    ply=1,
    san="e4",
    fen="f",
    wdl_win=500,
    wdl_draw=300,
    wdl_loss=200,
    wdl_win_adj=480,
    wdl_draw_adj=260,
    wdl_loss_adj=260,
    wdl_mu=0.1,
    delta_mu=0.02,
    delta_d=-0.05,
    cp_equiv=10,
    best_move="e4",
    arrow_uci="e2e4",
    move_win_delta=2.0,
    base_severity="Excellent",
    draw_character=None,
)

# ---------------------------------------------------------------------------
# Base game-level payload (no moves yet)
# ---------------------------------------------------------------------------

BASE_GAME = dict(
    worker_id="w",
    engine_nodes=25000,
    network_name="n",
    draw_rate_reference=0.58,
    wdl_calibration_elo=900,
    contempt=-400,
    white_win_prob=0.5,
    white_draw_prob=0.3,
    white_loss_prob=0.2,
    black_win_prob=0.4,
    black_draw_prob=0.3,
    black_loss_prob=0.3,
    white_blunders=0,
    white_mistakes=0,
    white_inaccuracies=1,
    black_blunders=0,
    black_mistakes=0,
    black_inaccuracies=0,
)


def test_accepts_new_fields():
    """Full happy-path: all new WDL-calibration fields accepted."""
    payload = {**BASE_GAME, "moves": [BASE_MOVE]}
    s = Lc0CompleteSerializer(data=payload)
    assert s.is_valid(), s.errors


def test_rejects_unknown_base_severity():
    """base_severity values outside LC0_SEVERITY_CHOICES must be rejected."""
    bad = {**BASE_MOVE, "base_severity": "Brilliant"}
    payload = {**BASE_GAME, "moves": [bad]}
    s = Lc0CompleteSerializer(data=payload)
    assert not s.is_valid()


def test_accepts_all_severity_choices():
    """Every valid severity string must be accepted."""
    valid_severities = ["Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder"]
    for severity in valid_severities:
        move = {**BASE_MOVE, "base_severity": severity}
        s = Lc0CompleteSerializer(data={**BASE_GAME, "moves": [move]})
        assert s.is_valid(), f"Expected {severity!r} to be valid; errors: {s.errors}"


def test_accepts_draw_character_choices():
    """All draw_character enum values (and None) must be accepted."""
    valid_chars = ["Missed Win", "Losing Blunder", "Risky", "Simplification", None]
    for dc in valid_chars:
        move = {**BASE_MOVE, "draw_character": dc}
        s = Lc0CompleteSerializer(data={**BASE_GAME, "moves": [move]})
        assert s.is_valid(), f"Expected draw_character={dc!r} to be valid; errors: {s.errors}"


def test_delta_d_can_be_negative():
    """delta_d is a signed float — negative values (draw fraction fell) must be accepted."""
    move = {**BASE_MOVE, "delta_d": -0.99}
    s = Lc0CompleteSerializer(data={**BASE_GAME, "moves": [move]})
    assert s.is_valid(), s.errors


def test_wdl_mu_optional():
    """wdl_mu is nullable/optional — omitting it should not cause a validation error."""
    move = {**BASE_MOVE}
    move.pop("wdl_mu")
    s = Lc0CompleteSerializer(data={**BASE_GAME, "moves": [move]})
    assert s.is_valid(), s.errors


def test_contempt_can_be_negative():
    """contempt can be a negative integer (engine is playing for a draw)."""
    payload = {**BASE_GAME, "contempt": -400, "moves": [BASE_MOVE]}
    s = Lc0CompleteSerializer(data=payload)
    assert s.is_valid(), s.errors
