"""
Title: test_chip_data.py — Tests for per-ply chip data assembly
Description:
    Verifies that chips_for_ply returns the correct chip dicts for a given
    ply, and returns an empty list for plies with no engine data.
    Also unit-tests _this_move_context for is_book and opening pass-through.

Changelog:
    2026-05-21 (#186): Initial.
    2026-05-29 (#226): Add _this_move_context is_book and opening-field tests.
"""
import types

import pytest
from games.chip_data import chips_for_ply
from games.services_v2 import get_game_analysis_v2
from games.views import _this_move_context

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


def _make_stub_data(book_ply_count=3, opening_common_name="Ruy Lopez", opening_book_id=42):
    """Return a lightweight SimpleNamespace stub matching the fields _this_move_context reads.

    Parameters:
        book_ply_count (int): Number of opening-book plies.
        opening_common_name (str): Human-readable opening name.
        opening_book_id (int | None): OpeningBook primary key.

    Returns:
        SimpleNamespace: Stub with book_ply_count, opening_common_name, opening_book_id,
            sf_moves, and lc0_moves attributes (empty lists — no delta computation needed).
    """
    return types.SimpleNamespace(
        book_ply_count=book_ply_count,
        opening_common_name=opening_common_name,
        opening_book_id=opening_book_id,
        sf_moves=[],
        lc0_moves=[],
    )


def test_this_move_context_is_book_true_for_book_ply():
    """is_book is True when 0 < ply <= book_ply_count."""
    data = _make_stub_data(book_ply_count=3)
    ctx = _this_move_context(data, ply=2)
    assert ctx["is_book"] is True


def test_this_move_context_is_book_false_beyond_book_ply():
    """is_book is False when ply > book_ply_count."""
    data = _make_stub_data(book_ply_count=3)
    ctx = _this_move_context(data, ply=4)
    assert ctx["is_book"] is False


def test_this_move_context_is_book_false_at_ply_zero():
    """is_book is False at ply 0 (start position, the early-return branch)."""
    data = _make_stub_data(book_ply_count=3)
    ctx = _this_move_context(data, ply=0)
    assert ctx["is_book"] is False


def test_this_move_context_opening_fields_passed_through():
    """opening_common_name and opening_id are passed through from data to context."""
    data = _make_stub_data(opening_common_name="Sicilian Defence", opening_book_id=7)
    ctx = _this_move_context(data, ply=2)
    assert ctx["opening_common_name"] == "Sicilian Defence"
    assert ctx["opening_id"] == 7


def test_this_move_context_opening_fields_at_ply_zero():
    """Opening fields are also present in the ply<=0 early-return dict."""
    data = _make_stub_data(opening_common_name="Queen's Gambit", opening_book_id=None)
    ctx = _this_move_context(data, ply=0)
    assert ctx["opening_common_name"] == "Queen's Gambit"
    assert ctx["opening_id"] is None
