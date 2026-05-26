"""
Title: test_load_board_inputs.py — Tests for services_v2.load_board_inputs
Description:
    Verifies that load_board_inputs returns a (pgn, sf_moves, lc0_moves) triple
    suitable for build_board_frames.

Changelog:
    2026-05-26 (#209): Initial — supports board_builder v2 cutover.
"""
import pytest
from games.services_v2 import SfMoveRow, Lc0MoveRow, load_board_inputs

pytestmark = pytest.mark.django_db


def test_load_board_inputs_returns_pgn_and_typed_lists(simple_pgn_game):
    """Returns the game's PGN plus typed dataclass lists for each engine.

    Parameters:
        simple_pgn_game: Fixture game exposing a parsable .pgn.
    """
    pgn, sf_moves, lc0_moves = load_board_inputs(simple_pgn_game)
    assert isinstance(pgn, str) and pgn  # non-empty
    assert all(isinstance(r, SfMoveRow) for r in sf_moves)
    assert all(isinstance(r, Lc0MoveRow) for r in lc0_moves)
