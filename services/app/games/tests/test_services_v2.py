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
