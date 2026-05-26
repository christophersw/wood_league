"""
Title: test_services_v2.py — Tests for the new-schema-only analysis loader
Description:
    Verifies that get_game_analysis_v2 returns None for missing games,
    None for legacy (pre-derived-fields) games, and a fully populated
    GameAnalysisDataV2 for games with the new schema fields present.

Changelog:
    2026-05-21 (#186): Initial.
"""
import pytest
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_returns_none_for_missing_game():
    """A slug that doesn't exist in the DB must return None."""
    assert get_game_analysis_v2("nope-not-real") is None


def test_returns_none_when_no_derived_fields(legacy_game_factory):
    """A game whose SF moves lack move_win_delta and whose LC0 moves
    lack wdl_win_adj is treated as legacy — return None so the view
    can show the re-analyze banner."""
    game = legacy_game_factory()
    assert get_game_analysis_v2(game.slug) is None


def test_returns_populated_dataclass_for_new_schema(new_schema_game_factory):
    """A game with fully derived SF and LC0 fields returns a populated dataclass."""
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    assert data is not None
    assert data.has_sf is True
    assert data.has_lc0 is True
    # New-schema-only fields
    assert data.sf_moves[0].move_win_delta is not None
    assert data.lc0_moves[0].wdl_win_adj is not None
    assert data.lc0_moves[0].draw_character is not None or data.lc0_moves[0].base_severity is not None
    assert data.lc0_white_accuracy is not None


def test_lc0_move_row_carries_raw_and_candidate_wdl(new_schema_game_factory):
    """Lc0MoveRow exposes raw played WDL and per-candidate WDL triples for arrows.

    Parameters:
        new_schema_game_factory: Factory fixture producing a new-schema game.
    """
    from games.services_v2 import get_game_analysis_v2
    game = new_schema_game_factory()
    data = get_game_analysis_v2(game.slug)
    row = next(m for m in data.lc0_moves if m.ply == 1)
    # Per #209 / PR #210 L2, the LC0 fixture now sets every per-candidate WDL
    # triple equal to the played triple so _lc0_candidate_delta_mu returns 0.0
    # (non-None) and the LC0 arrow-label path is exercised by every test. The
    # exact-value assertion still guards against (win/draw/loss) channel
    # transposition in the loader; tests needing distinct candidates should
    # override these fields in-place rather than rely on the factory defaults.
    assert (row.wdl_win, row.wdl_draw, row.wdl_loss) == (530, 290, 180)
    assert (row.wdl_win_1, row.wdl_draw_1, row.wdl_loss_1) == (530, 290, 180)
    assert (row.wdl_win_2, row.wdl_draw_2, row.wdl_loss_2) == (530, 290, 180)
    assert (row.wdl_win_3, row.wdl_draw_3, row.wdl_loss_3) == (530, 290, 180)
