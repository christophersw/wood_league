"""
Title: test_models_phase_f_rebuild.py — Drop-and-rebuild model shape (#161 F)
Description:
    Issue #161 Phase F. Pins the post-rebuild column set for all four analysis
    models. The migration drops every existing row (per spec: "no backfill, no
    compat shim") and recreates the tables with raw + derived fields side by
    side, ready for the Phase G serializers to feed via ``derivation``.

    Old-name fields like ``arrow_uci`` (now ``arrow_uci_1``) and
    ``cp_equiv`` (removed entirely from lc0) are guarded against
    reintroduction.

Changelog:
    2026-05-20 (#161/F): Initial.
"""
from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from analysis.models import (
    GameAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    MoveAnalysis,
)
from games.models import Game


def _make_game() -> Game:
    """Create a unique Game so each test FK references its own row."""
    return Game.objects.create(
        id=f"phaseF-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )


# ── MoveAnalysis (Stockfish) ─────────────────────────────────────────────


@pytest.mark.django_db
def test_sf_move_has_new_raw_and_derived_fields():
    """Stockfish MoveAnalysis carries ``mate_in``, ``move_win_delta``, ``arrow_uci_1``."""
    game = _make_game()
    ga = GameAnalysis.objects.create(game=game, engine_depth=20, summary_cp=0)
    move = MoveAnalysis.objects.create(
        analysis=ga, ply=1, san="e4", fen="—",
        cp_eval=30, cpl=0,
        arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=30.0, arrow_cp_2=12.0, arrow_cp_3=None,
        mate_in=None,
        move_win_delta=0.0,
        classification="Best",
    )
    move.refresh_from_db()
    assert move.arrow_uci_1 == "e2e4"
    assert move.mate_in is None
    assert move.move_win_delta == pytest.approx(0.0)


@pytest.mark.django_db
def test_sf_move_legacy_arrow_uci_field_removed():
    """The pre-#161 ``arrow_uci`` field is gone — only ``arrow_uci_1`` remains."""
    assert not hasattr(MoveAnalysis, "arrow_uci"), (
        "MoveAnalysis.arrow_uci must be renamed to arrow_uci_1 in Phase F"
    )


@pytest.mark.django_db
def test_sf_move_mate_in_round_trips_signed():
    """``mate_in`` is signed and nullable; positive = White mates, negative = Black."""
    game = _make_game()
    ga = GameAnalysis.objects.create(game=game, engine_depth=20, summary_cp=0)
    move = MoveAnalysis.objects.create(
        analysis=ga, ply=2, san="—", fen="—",
        cp_eval=0, cpl=0,
        arrow_uci_1="—",
        mate_in=-3,
    )
    move.refresh_from_db()
    assert move.mate_in == -3


# ── Lc0MoveAnalysis ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_lc0_move_has_per_candidate_wdl_triples():
    """Lc0MoveAnalysis stores raw WDL for the played move and three candidates."""
    game = _make_game()
    lga = Lc0GameAnalysis.objects.create(
        game=game, engine_nodes=25000, network_name="net",
    )
    move = Lc0MoveAnalysis.objects.create(
        analysis=lga, ply=1, san="e4", fen="—",
        wdl_win=500, wdl_draw=300, wdl_loss=200,
        wdl_win_1=510, wdl_draw_1=290, wdl_loss_1=200,
        wdl_win_2=480, wdl_draw_2=310, wdl_loss_2=210,
        wdl_win_3=460, wdl_draw_3=320, wdl_loss_3=220,
        arrow_uci_1="e2e4", arrow_uci_2="d2d4", arrow_uci_3="c2c4",
        wdl_win_adj=502, wdl_draw_adj=290, wdl_loss_adj=208,
        wdl_mu=0.55, delta_mu=None, delta_d=None,
        base_severity="Best", draw_character=None,
    )
    move.refresh_from_db()
    for n in (1, 2, 3):
        assert getattr(move, f"wdl_win_{n}") > 0
        assert getattr(move, f"wdl_draw_{n}") > 0
        assert getattr(move, f"wdl_loss_{n}") > 0


@pytest.mark.django_db
def test_lc0_move_per_candidate_wdl_is_nullable():
    """A move with only one candidate stores nulls for the other two lines."""
    game = _make_game()
    lga = Lc0GameAnalysis.objects.create(
        game=game, engine_nodes=25000, network_name="net",
    )
    move = Lc0MoveAnalysis.objects.create(
        analysis=lga, ply=1, san="e4", fen="—",
        wdl_win=500, wdl_draw=300, wdl_loss=200,
        wdl_win_1=510, wdl_draw_1=290, wdl_loss_1=200,
        wdl_win_2=None, wdl_draw_2=None, wdl_loss_2=None,
        wdl_win_3=None, wdl_draw_3=None, wdl_loss_3=None,
        arrow_uci_1="e2e4",
    )
    move.refresh_from_db()
    assert move.wdl_win_2 is None
    assert move.wdl_loss_3 is None


def test_lc0_move_removed_legacy_fields():
    """Phase F deletes ``cp_equiv``, ``arrow_score_*``, ``move_win_delta``, ``arrow_uci``."""
    removed = (
        "cp_equiv",
        "arrow_score_1", "arrow_score_2", "arrow_score_3",
        "move_win_delta",
        "arrow_uci",
    )
    for name in removed:
        assert not hasattr(Lc0MoveAnalysis, name), (
            f"Lc0MoveAnalysis.{name} must be removed in Phase F"
        )


# ── GameAnalysis (Stockfish) & Lc0GameAnalysis: shape unchanged ──────────


def test_sf_game_analysis_field_set_unchanged():
    """SF GameAnalysis already matches the derive_sf_game output — pin the field set."""
    field_names = {f.name for f in GameAnalysis._meta.get_fields()}
    for expected in (
        "engine_depth", "summary_cp",
        "white_accuracy", "black_accuracy",
        "white_acpl", "black_acpl",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
    ):
        assert expected in field_names, expected


def test_lc0_game_analysis_field_set_unchanged():
    """Lc0 GameAnalysis already matches derive_lc0_game output — pin the field set."""
    field_names = {f.name for f in Lc0GameAnalysis._meta.get_fields()}
    for expected in (
        "engine_nodes", "network_name",
        "draw_rate_reference", "wdl_calibration_elo", "contempt",
        "white_win_prob", "white_draw_prob", "white_loss_prob",
        "black_win_prob", "black_draw_prob", "black_loss_prob",
        "white_blunders", "white_mistakes", "white_inaccuracies",
        "black_blunders", "black_mistakes", "black_inaccuracies",
    ):
        assert expected in field_names, expected
