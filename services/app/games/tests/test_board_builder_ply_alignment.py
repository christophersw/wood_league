"""
Title: test_board_builder_ply_alignment.py — Regression tests for board-builder ply alignment
Description:
    Verifies that build_board_frames, when called with new-dataclass SfMoveRow /
    Lc0MoveRow lists, maps each analysis row to the correct displayed ply.
    Exercises the fix for the positional zip/enumerate bug where LC0 rows
    starting at a different first ply from SF were assigned to the wrong frame.
    Also verifies v2 frames are self-contained (svg, ply, san, last_move_uci,
    classification in every frame).

Changelog:
    2026-05-21 (#186): Initial — ply-alignment regression test.
    2026-05-26 (#209): Add test_v2_frames_are_self_contained.
    2026-05-26 (#209 Task 7): Update test_v2_result_has_player_layout_and_engine_flags
                              to assert flat keys (not nested player_layout dict).
"""
import pytest
from games.board_builder import build_board_frames
from games.services_v2 import SfMoveRow, Lc0MoveRow

pytestmark = pytest.mark.django_db


def _sf(ply, uci):
    """Build a minimal SfMoveRow with the given ply and primary arrow UCI.

    Parameters:
        ply (int): Ply number (1-indexed).
        uci (str): Arrow UCI string for arrow_uci_1.

    Returns:
        SfMoveRow: A minimal row with only the required fields set.
    """
    return SfMoveRow(
        ply=ply, san=f"M{ply}", fen="",
        cp_eval=0.0, mate_in=None, cpl=0.0, move_win_delta=0.0,
        classification="best", best_move="", arrow_uci_1=uci,
        arrow_uci_2=None, arrow_uci_3=None,
        arrow_cp_1=0.0, arrow_cp_2=None, arrow_cp_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )


def _lc0(ply, uci):
    """Build a minimal Lc0MoveRow with the given ply and primary arrow UCI.

    Parameters:
        ply (int): Ply number (1-indexed).
        uci (str): Arrow UCI string for arrow_uci_1.

    Returns:
        Lc0MoveRow: A minimal row with only the required fields set.
    """
    return Lc0MoveRow(
        ply=ply, san=f"M{ply}", fen="",
        wdl_win_adj=500, wdl_draw_adj=300, wdl_loss_adj=200,
        wdl_mu=0.5, delta_mu=0.0, delta_d=0.0,
        base_severity="best", draw_character=None, best_move="",
        arrow_uci_1=uci, arrow_uci_2=None, arrow_uci_3=None,
        pv_san_1=None, pv_san_2=None, pv_san_3=None,
    )


def test_arrow_at_ply_matches_source_ply(simple_pgn_game):
    """A 4-ply PGN with SF arrows e2e4/d2d4/g1f3/b1c3 and LC0 starting at ply 3
    must render ply-3 arrows from the LC0 ply-3 row, not LC0 ply-1.

    Parameters:
        simple_pgn_game: pytest fixture — a Game with a 4-ply PGN.
    """
    sf = [_sf(1, "e2e4"), _sf(2, "e7e5"), _sf(3, "g1f3"), _sf(4, "b8c6")]
    lc0 = [_lc0(3, "g1f3"), _lc0(4, "b8c6")]   # LC0 misses the first two plies
    frames = build_board_frames(
        pgn=simple_pgn_game.pgn,
        sf_moves=sf,
        lc0_moves=lc0,
        orientation="white",
    )
    # Frame for ply 3: SF arrow g1f3, LC0 arrow g1f3
    ply3 = frames["frames"][3]
    sf_arrows = [a for a in ply3["arrows"] if a["engine"] == "sf"]
    lc0_arrows = [a for a in ply3["arrows"] if a["engine"] == "lc0"]
    assert sf_arrows and sf_arrows[0]["uci"] == "g1f3"
    assert lc0_arrows and lc0_arrows[0]["uci"] == "g1f3"
    # Frame for ply 1: SF arrow e2e4, NO LC0 arrow (no LC0 data for ply 1).
    ply1 = frames["frames"][1]
    assert any(a["engine"] == "sf" and a["uci"] == "e2e4" for a in ply1["arrows"])
    assert not any(a["engine"] == "lc0" for a in ply1["arrows"])


_SELF_CONTAINED_SF_ROW = SfMoveRow(
    ply=1, san="e4", fen="", cp_eval=20.0, mate_in=None, cpl=0.0,
    move_win_delta=0.0, classification="best", best_move="",
    arrow_uci_1=None, arrow_uci_2=None, arrow_uci_3=None,
    arrow_cp_1=None, arrow_cp_2=None, arrow_cp_3=None,
    pv_san_1=None, pv_san_2=None, pv_san_3=None,
)


def _build_self_contained_frames(pgn):
    """Render v2 frames for the start-position + ply-1 self-contained-frame tests."""
    return build_board_frames(
        pgn=pgn, sf_moves=[_SELF_CONTAINED_SF_ROW], lc0_moves=[], orientation="white",
    )["frames"]


def test_v2_start_frame_has_no_move_metadata(simple_pgn_game):
    """Ply-0 (start position) carries None for san/last_move_uci/classification.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    frames = _build_self_contained_frames(simple_pgn_game.pgn)
    start = frames[0]
    assert start == {**start, "ply": 0, "san": None, "last_move_uci": None, "classification": None}
    assert isinstance(start["svg"], str) and start["svg"].startswith("<svg")


def test_v2_ply1_frame_carries_move_metadata(simple_pgn_game):
    """Ply-1 (first move) carries SAN, UCI, and classification sourced from the SF row.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    frames = _build_self_contained_frames(simple_pgn_game.pgn)
    ply1 = frames[1]
    expected = {"ply": 1, "san": "e4", "last_move_uci": "e2e4", "classification": "best"}
    assert ply1 == {**ply1, **expected}
    assert isinstance(ply1["svg"], str) and ply1["svg"].startswith("<svg")
    assert isinstance(frames[1]["svg"], str) and frames[1]["svg"].startswith("<svg")


def test_v2_result_has_overlay_geometry(simple_pgn_game):
    """v2 build_board_frames exposes the overlay-geometry dict the JS reads.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [_SELF_CONTAINED_SF_ROW]
    result = build_board_frames(
        pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white", size=480,
    )
    geom = result["overlay_geometry"]
    assert {"viewbox_size", "board_margin", "square_size"} <= set(geom.keys())


def test_v2_result_has_player_layout_and_engine_flags(simple_pgn_game):
    """v2 build_board_frames exposes flat player keys (top_side/bottom_side/etc) and has_sf/has_lc0.

    After Task 7 (#209) the nested player_layout dict was replaced by the flat
    legacy-compatible key contract: top_player, top_sym, top_side,
    bottom_player, bottom_sym, bottom_side — all at the top level of the result.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    sf = [_SELF_CONTAINED_SF_ROW]
    result = build_board_frames(
        pgn=simple_pgn_game.pgn, sf_moves=sf, lc0_moves=[], orientation="white", size=480,
    )
    # Flat keys at top level — no nested player_layout dict.
    assert {"top_side", "bottom_side", "top_player", "bottom_player", "top_sym", "bottom_sym"} <= set(result.keys())
    assert "player_layout" not in result, "player_layout nested dict should be gone after Task 7 cutover"
    assert result["has_sf"] is True
    assert result["has_lc0"] is False
