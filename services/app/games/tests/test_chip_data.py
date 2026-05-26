"""
Title: test_chip_data.py — Tests for per-ply chip data assembly
Description:
    Verifies that chips_for_ply returns the correct chip dicts for a given
    ply, and returns an empty list for plies with no engine data.

Changelog:
    2026-05-21 (#186): Initial.
"""
import pytest
from games.chip_data import chips_for_ply
from games.services_v2 import get_game_analysis_v2

pytestmark = pytest.mark.django_db


def test_chips_includes_all_three_levels(new_schema_game_factory):
    """chips_for_ply returns SF + LC0 base chips; LC0 draw chip when populated."""
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    chips = chips_for_ply(data, ply=data.sf_moves[0].ply)
    kinds = {c["kind"] for c in chips}
    # SF classification + LC0 base severity must be present
    assert "sf" in kinds
    assert "lc0_base" in kinds


def test_chips_empty_for_unknown_ply(new_schema_game_factory):
    """chips_for_ply returns [] when no engine data exists for the requested ply."""
    data = get_game_analysis_v2(new_schema_game_factory().slug)
    assert chips_for_ply(data, ply=9999) == []


def test_chips_carry_engine_source():
    """Each chip dict exposes a human engine source: SF for Stockfish, LC0 for Leela."""
    from games.chip_data import _chip
    assert _chip("sf", "Blunder", "t")["source"] == "SF"
    assert _chip("lc0_base", "Mistake", "t")["source"] == "LC0"
    assert _chip("lc0_draw", "Simplification", "t")["source"] == "LC0"
