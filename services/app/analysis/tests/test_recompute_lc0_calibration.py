"""
Title: test_recompute_lc0_calibration.py — Tests for recompute_lc0_calibration command
Description:
    Verifies that the recompute_lc0_calibration management command correctly
    recomputes Lc0MoveAnalysis derived fields (wdl_*_adj, wdl_mu, delta_mu,
    delta_d, base_severity, draw_character) from stored raw WDL triples and
    per-game calibration metadata, without invoking any chess engine. Also
    verifies that the command does not import chess.engine (no engine dependency).

Changelog:
    2026-05-19 (#159/E1): Initial — TDD Step 1 failing test.
"""
import uuid

import pytest
from django.core.management import call_command
from django.utils import timezone

from analysis.models import Lc0GameAnalysis, Lc0MoveAnalysis
from games.models import Game

_VALID_SEVERITY = {"Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder"}


def _make_game() -> Game:
    """Create a minimal Game instance with unique ID for FK use.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"test-E1-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )


@pytest.mark.django_db
def test_recompute_is_pure_from_stored_raw():
    """--all flag recomputes wdl_*_adj and base_severity from stored raw WDL.

    Creates an Lc0GameAnalysis with draw_rate_reference=0.58 and an
    Lc0MoveAnalysis with adj fields zeroed.  After call_command the adj
    fields must be non-zero and base_severity must be a valid severity label.
    """
    game = _make_game()
    a = Lc0GameAnalysis.objects.create(
        game=game,
        engine_nodes=1,
        network_name="t",
        draw_rate_reference=0.58,
        wdl_calibration_elo=900,
        contempt=-400,
    )
    m = Lc0MoveAnalysis.objects.create(
        analysis=a,
        ply=1,
        san="e4",
        fen="f",
        wdl_win=500,
        wdl_draw=300,
        wdl_loss=200,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=10,
        best_move="e4",
        base_severity="Best",
        draw_character=None,
    )
    call_command("recompute_lc0_calibration", "--all")
    m.refresh_from_db()
    assert (m.wdl_win_adj, m.wdl_draw_adj, m.wdl_loss_adj) != (0, 0, 0), (
        "Rescaled adj triple must differ from the zero placeholder"
    )
    assert m.base_severity in _VALID_SEVERITY, (
        f"base_severity={m.base_severity!r} is not a valid severity label"
    )


@pytest.mark.django_db
def test_recompute_single_game():
    """--game <id> recomputes only the specified Lc0GameAnalysis.

    Creates two game analyses.  Recomputing only one must leave the other
    untouched (wdl_win_adj stays at 0 for the untouched game).
    """
    game1 = _make_game()
    game2 = _make_game()

    a1 = Lc0GameAnalysis.objects.create(
        game=game1,
        engine_nodes=1,
        network_name="t",
        draw_rate_reference=0.58,
        wdl_calibration_elo=1100,
        contempt=0,
    )
    Lc0MoveAnalysis.objects.create(
        analysis=a1,
        ply=1,
        san="e4",
        fen="f1",
        wdl_win=500,
        wdl_draw=300,
        wdl_loss=200,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=10,
        best_move="e4",
        base_severity="Best",
        draw_character=None,
    )

    a2 = Lc0GameAnalysis.objects.create(
        game=game2,
        engine_nodes=1,
        network_name="t",
        draw_rate_reference=0.58,
        wdl_calibration_elo=1100,
        contempt=0,
    )
    m2 = Lc0MoveAnalysis.objects.create(
        analysis=a2,
        ply=1,
        san="d4",
        fen="f2",
        wdl_win=490,
        wdl_draw=320,
        wdl_loss=190,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=5,
        best_move="d4",
        base_severity="Best",
        draw_character=None,
    )

    # Recompute only a1 (game1)
    call_command("recompute_lc0_calibration", "--game", str(a1.id))

    # a2's move must remain untouched
    m2.refresh_from_db()
    assert (m2.wdl_win_adj, m2.wdl_draw_adj, m2.wdl_loss_adj) == (0, 0, 0), (
        "Move in non-targeted game must not be modified"
    )


@pytest.mark.django_db
def test_recompute_skips_missing_draw_rate():
    """Games without draw_rate_reference are skipped gracefully.

    draw_rate_reference=None means the game cannot be rescaled offline.
    The command must not raise and must leave the move unchanged.
    """
    game = _make_game()
    a = Lc0GameAnalysis.objects.create(
        game=game,
        engine_nodes=1,
        network_name="t",
        draw_rate_reference=None,
        wdl_calibration_elo=1000,
        contempt=0,
    )
    m = Lc0MoveAnalysis.objects.create(
        analysis=a,
        ply=1,
        san="e4",
        fen="f",
        wdl_win=500,
        wdl_draw=300,
        wdl_loss=200,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=10,
        best_move="e4",
        base_severity="Best",
        draw_character=None,
    )
    # Must not raise even when draw_rate_reference is None
    call_command("recompute_lc0_calibration", "--all")
    m.refresh_from_db()
    # Move is left as-is since the game cannot be rescaled
    assert (m.wdl_win_adj, m.wdl_draw_adj, m.wdl_loss_adj) == (0, 0, 0)


def test_command_module_has_no_chess_engine_import():
    """The command module must not import chess.engine (no engine dependency).

    Reads the source file as text and asserts that the literal string
    'import chess.engine' does not appear.
    """
    import pathlib

    cmd_path = pathlib.Path(__file__).resolve().parent.parent / (
        "management/commands/recompute_lc0_calibration.py"
    )
    assert cmd_path.is_file(), f"Command file not found at {cmd_path}"
    source = cmd_path.read_text()
    assert "import chess.engine" not in source, (
        "Command module must not import chess.engine — it is a pure DB recompute"
    )


@pytest.mark.django_db
def test_recompute_two_move_game_delta_mu():
    """delta_mu for the second move is computed relative to ply 1's raw WDL.

    Creates a 2-ply game analysis.  After recompute, ply 2's delta_mu must
    be a float (not None) since the pre-move WDL is the stored raw of ply 1.
    """
    game = _make_game()
    a = Lc0GameAnalysis.objects.create(
        game=game,
        engine_nodes=1,
        network_name="t",
        draw_rate_reference=0.58,
        wdl_calibration_elo=1100,
        contempt=0,
    )
    Lc0MoveAnalysis.objects.create(
        analysis=a,
        ply=1,
        san="e4",
        fen="f1",
        wdl_win=500,
        wdl_draw=300,
        wdl_loss=200,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=10,
        best_move="e4",
        base_severity="Best",
        draw_character=None,
    )
    m2 = Lc0MoveAnalysis.objects.create(
        analysis=a,
        ply=2,
        san="e5",
        fen="f2",
        wdl_win=200,
        wdl_draw=300,
        wdl_loss=500,
        wdl_win_adj=0,
        wdl_draw_adj=0,
        wdl_loss_adj=0,
        wdl_mu=None,
        delta_mu=None,
        delta_d=None,
        cp_equiv=-10,
        best_move="e5",
        base_severity="Best",
        draw_character=None,
    )
    call_command("recompute_lc0_calibration", "--all")
    m2.refresh_from_db()
    assert m2.delta_mu is not None, (
        "delta_mu for ply 2 must be a float, computed from ply 1 raw WDL"
    )
