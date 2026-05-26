"""
Title: test_arrow_labels.py — Tests for board arrow label generation
Description:
    Verifies that arrows emitted by build_board_frames carry a human-readable
    `label` field: "SF ±<pawns>" for Stockfish arrows and "Lc0 ±<pct>%" for
    LC0 arrows.  Uses the `simple_pgn_game` fixture from conftest.

Changelog:
    2026-05-21 (#186): Initial — Task 13 of game-analysis-rewrite.
"""
import pytest
from games.board_builder import build_board_frames
from games.services_v2 import SfMoveRow, Lc0MoveRow

pytestmark = pytest.mark.django_db


def test_sf_arrow_has_signed_pawn_label(simple_pgn_game):
    """SF arrow label is 'SF +<pawns>' with 2 decimal places."""
    sf = [SfMoveRow(
        ply=1, san="e4", fen="", cp_eval=34.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=34.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"] == "SF +0.34"


def test_lc0_arrow_has_signed_winpct_label(simple_pgn_game):
    """LC0 arrow label starts with 'Lc0 ' and contains '%'."""
    # delta_mu=-0.12 means candidate is 12% worse than played → Lc0 −12%
    lc0 = [Lc0MoveRow(
        ply=1, san="e4", fen="", wdl_win_adj=600, wdl_draw_adj=300, wdl_loss_adj=100,
        wdl_mu=0.75, delta_mu=-0.12, delta_d=0.0,
        base_severity="best", draw_character=None, best_move="",
        arrow_uci_1="e2e4", arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )]
    frames = build_board_frames(pgn=simple_pgn_game.pgn, sf_moves=[], lc0_moves=lc0, orientation="white")
    arrow = frames["frames"][1]["arrows"][0]
    assert arrow["label"].startswith("Lc0 ")
    assert "%" in arrow["label"]


def test_v2_arrow_entry_has_color_opacity_stroke(simple_pgn_game):
    """Each v2 arrow entry carries engine color, opacity, and stroke width."""
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
