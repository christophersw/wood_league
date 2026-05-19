"""
Title: test_lc0_calibration_models.py — Tests for Lc0 WDL calibration model fields
Description:
    Verifies that Lc0GameAnalysis and Lc0MoveAnalysis correctly persist the new
    WDL calibration columns introduced in issue #159 (D3): draw_rate_reference,
    wdl_calibration_elo, contempt on the game level; wdl_win_adj, wdl_draw_adj,
    wdl_loss_adj, wdl_mu, delta_mu, delta_d, base_severity, draw_character on
    the move level. Also verifies that the old `classification` field has been
    replaced by `base_severity` + `draw_character`.

Changelog:
    2026-05-19 (#159/D3): Initial — Step 1 failing test for TDD cycle.
"""
import uuid

import pytest
from django.utils import timezone

from analysis.models import Lc0GameAnalysis, Lc0MoveAnalysis
from games.models import Game


def _make_game() -> Game:
    """Create a minimal Game instance for use as an FK target.

    Returns:
        Game: A saved Game instance with a unique ID.
    """
    return Game.objects.create(
        id=f"test-D3-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )


@pytest.mark.django_db
def test_new_fields_persist():
    """New calibration columns round-trip correctly through the DB.

    Creates an Lc0GameAnalysis with calibration metadata and an Lc0MoveAnalysis
    with the rescaled WDL triple, severity labels, and delta metrics.  After
    refresh_from_db both rows must return the exact values that were written.
    """
    game = _make_game()
    a = Lc0GameAnalysis.objects.create(
        game=game,
        engine_nodes=25000,
        network_name="t",
        draw_rate_reference=0.58,
        wdl_calibration_elo=900,
        contempt=-400,
    )
    m = Lc0MoveAnalysis.objects.create(
        analysis=a,
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
        base_severity="Excellent",
        draw_character=None,
    )
    m.refresh_from_db()
    assert m.wdl_win_adj == 480
    assert m.base_severity == "Excellent"
    assert m.draw_character is None
    assert m.wdl_mu == pytest.approx(0.1)
    assert m.delta_mu == pytest.approx(0.02)
    assert m.delta_d == pytest.approx(-0.05)

    a.refresh_from_db()
    assert a.draw_rate_reference == pytest.approx(0.58)
    assert a.wdl_calibration_elo == 900
    assert a.contempt == -400


@pytest.mark.django_db
def test_classification_field_removed():
    """The old `classification` column must not exist on Lc0MoveAnalysis.

    This guards against regressions where the old field is accidentally kept
    alongside the new ones.
    """
    assert not hasattr(
        Lc0MoveAnalysis, "classification"
    ), "Lc0MoveAnalysis.classification field was not removed — it should be replaced by base_severity + draw_character"


@pytest.mark.django_db
def test_nullable_calibration_fields():
    """Calibration fields default to NULL and can be set to None explicitly.

    The worker emits draw_character=None for most moves (only set when the move
    crosses a draw-character threshold).  wdl_mu/delta_mu/delta_d can also be
    None in degenerate WDL paths.
    """
    game = _make_game()
    a = Lc0GameAnalysis.objects.create(
        game=game,
        engine_nodes=1000,
        network_name="net",
    )
    m = Lc0MoveAnalysis.objects.create(
        analysis=a,
        ply=2,
        san="e5",
        fen="g",
        best_move="e5",
        wdl_win=333,
        wdl_draw=333,
        wdl_loss=334,
        wdl_win_adj=None,
        wdl_draw_adj=None,
        wdl_loss_adj=None,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        base_severity="Good",
        draw_character=None,
    )
    m.refresh_from_db()
    assert m.wdl_win_adj is None
    assert m.wdl_mu is None
    assert m.draw_character is None
    assert m.base_severity == "Good"
    # Game-level calibration fields also nullable
    a.refresh_from_db()
    assert a.draw_rate_reference is None
    assert a.wdl_calibration_elo is None
    assert a.contempt is None
