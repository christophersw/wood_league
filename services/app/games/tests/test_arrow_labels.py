"""
Title: test_arrow_labels.py — Tests for board arrow label generation
Description:
    Verifies that arrows emitted by build_board_frames carry a human-readable
    `label` field: delta-vs-played for both engines. SF shows the mover-relative
    cp delta (candidate cp − played cp) in pawns. LC0 shows the candidate
    expected-score mu delta vs the played mu in win%. The engine is conveyed by
    arrow colour, not by a text prefix.

Changelog:
    2026-05-21 (#186): Initial — Task 13 of game-analysis-rewrite.
    2026-05-26 (#209 Task 2.5): Port #208 delta-vs-played semantics to this branch.
"""
import pytest
from games.board_builder import build_board_frames, _UNICODE_MINUS
from games.services_v2 import SfMoveRow, Lc0MoveRow

pytestmark = pytest.mark.django_db


def test_sf_arrow_label_is_delta_vs_played(simple_pgn_game):
    """SF arrow label is the candidate's mover-relative cp delta vs the played move, in pawns.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=65.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    # ply 1 = White's move; delta = (65 − 20)/100 = +0.45. No "SF " prefix.
    assert arrow["label"] == "+0.45", arrow


def test_sf_arrow_label_negative_delta_uses_unicode_minus(simple_pgn_game):
    """A candidate worse than the played move shows a unicode-minus signed delta.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=65.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=20.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == f"{_UNICODE_MINUS}0.45", arrow


def test_lc0_arrow_label_is_delta_vs_played(simple_pgn_game):
    """LC0 arrow label is the candidate's mover-relative win% delta vs the played move.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    # played mu = (500 + 200/2)/1000 = 0.60; candidate1 mu = (620 + 180/2)/1000 = 0.71
    # delta = +0.11 → "+11%"
    lc0 = [Lc0MoveRow(
        ply=1, san="e4", fen="", wdl_win_adj=None, wdl_draw_adj=None, wdl_loss_adj=None,
        wdl_mu=None, delta_mu=None, delta_d=None, base_severity="best", draw_character=None,
        best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
        wdl_win=500, wdl_draw=200, wdl_loss=300,
        wdl_win_1=620, wdl_draw_1=180, wdl_loss_1=200,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=[], lc0_moves=lc0, orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == "+11%", arrow
    assert "Lc0" not in arrow["label"]


def test_v2_arrow_entry_keeps_color_opacity_stroke(simple_pgn_game):
    """Color/opacity/stroke_width (from Task 2) survive the label-semantics rewrite.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=65.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert isinstance(arrow["color"], str) and arrow["color"].startswith("#"), arrow
    assert 0.42 <= arrow["opacity"] <= 0.98, arrow
    assert arrow["stroke_width"] == 7, arrow
