"""
Title: test_load_board_inputs.py — Tests for services_v2.load_board_inputs
Description:
    Verifies that load_board_inputs returns a (pgn, sf_moves, lc0_moves) triple
    suitable for build_board_frames.

Changelog:
    2026-05-26 (#209): Initial — supports board_builder v2 cutover.
    2026-05-26 (#209): PR #210 L1 — rewritten to use new_schema_game_factory (game
                       with real SF+LC0 analysis) instead of simple_pgn_game (no
                       analysis); adds real length assertions so the test is no longer
                       vacuously True when both lists are empty.
"""
import pytest
from games.services_v2 import SfMoveRow, Lc0MoveRow, load_board_inputs

pytestmark = pytest.mark.django_db


def test_load_board_inputs_returns_pgn_and_typed_lists(new_schema_game_factory):
    """Returns the game's PGN plus typed dataclass lists for each engine.

    Uses new_schema_game_factory which creates a game with 4 SF rows and 4
    LC0 rows so the assertions are non-vacuous.

    Parameters:
        new_schema_game_factory: Fixture factory that creates a Game with
            fully derived SF + LC0 analysis (4 moves per engine).
    """
    game = new_schema_game_factory()
    pgn, sf_moves, lc0_moves = load_board_inputs(game)
    assert isinstance(pgn, str) and pgn  # non-empty
    assert len(sf_moves) == 4 and all(isinstance(r, SfMoveRow) for r in sf_moves)
    assert len(lc0_moves) == 4 and all(isinstance(r, Lc0MoveRow) for r in lc0_moves)
