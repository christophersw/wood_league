"""
Title: conftest.py — Pytest fixtures for games test suite
Description:
    Provides shared fixtures for games app tests, including game factories
    for legacy (pre-derived-fields) and new-schema (fully derived) games.
    Used by test_services_v2.py and downstream partial/card/chart tests.

    Model imports are deferred inside fixtures (not at module level) so that
    this conftest can be loaded before Django's app registry is ready — the
    root conftest.py calls django.setup() inside pytest_configure, but that
    runs after all conftest.py files on the collection path are imported.

Changelog:
    2026-05-21 (#186): Initial — legacy_game_factory, legacy_sf_game_factory,
                       new_schema_game_factory for services_v2 tests.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

# A minimal 4-ply PGN used by board-builder and other tests.
_SIMPLE_PGN = (
    '[Event "Test"]\n'
    '[Site "?"]\n'
    '[Date "2026.01.01"]\n'
    '[Round "1"]\n'
    '[White "Alice"]\n'
    '[Black "Bob"]\n'
    '[Result "*"]\n'
    '[TimeControl "300+0"]\n'
    "\n"
    "1. e4 e5 2. Nf3 Nc6 *"
)

# Position FENs for each ply of the simple PGN above.
_FENS = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # ply 0 (start)
    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",  # ply 1: 1.e4
    "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",  # ply 2: 1...e5
    "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",  # ply 3: 2.Nf3
    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",  # ply 4: 2...Nc6
]


def _unique_slug():
    """Return a unique slug fragment safe for use as a game slug.

    Returns:
        str: A 12-character hex string from uuid4.
    """
    return uuid4().hex[:12]


def _make_game(slug=None):
    """Create and return a minimal Game instance.

    Parameters:
        slug (str | None): Explicit slug; generated via _unique_slug() if omitted.

    Returns:
        Game: The saved Game instance.
    """
    from games.models import Game  # deferred: Django must be set up first
    slug = slug or _unique_slug()
    return Game.objects.create(
        id=slug,
        slug=slug,
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="300+0",
        white_username="Alice",
        black_username="Bob",
        white_rating=1500,
        black_rating=1500,
        result_pgn="1-0",
        pgn=_SIMPLE_PGN,
    )


def _make_lc0_move_row(lga, ply, san, win_adj, draw_adj, loss_adj, mu, dmu, base_sev, draw_char):
    """Create a single Lc0MoveAnalysis row with the new-schema derived fields populated.

    Parameters:
        lga (Lc0GameAnalysis): The parent analysis record.
        ply (int): Move ply number (1-indexed).
        san (str): Standard algebraic notation for the move.
        win_adj (int): Adjusted win count in White-frame WDL.
        draw_adj (int): Adjusted draw count in White-frame WDL.
        loss_adj (int): Adjusted loss count in White-frame WDL.
        mu (float): Estimated Elo difference (mu).
        dmu (float): Delta mu (change in mu).
        base_sev (str): Base severity classification (e.g., "best", "inaccuracy").
        draw_char (str): Draw character classification (e.g., "balanced", "sharp").

    Returns:
        Lc0MoveAnalysis: The saved analysis row with all derived fields populated.
    """
    from analysis.models import Lc0MoveAnalysis  # deferred import
    return Lc0MoveAnalysis.objects.create(
        analysis=lga,
        ply=ply,
        san=san,
        fen=_FENS[ply] if ply < len(_FENS) else _FENS[-1],
        wdl_win=win_adj,
        wdl_draw=draw_adj,
        wdl_loss=loss_adj,
        wdl_win_adj=win_adj,
        wdl_draw_adj=draw_adj,
        wdl_loss_adj=loss_adj,
        wdl_mu=mu,
        delta_mu=dmu,
        delta_d=0.005,
        base_severity=base_sev,
        draw_character=draw_char,
        arrow_uci_1="e2e4" if ply == 1 else "e7e5" if ply == 2 else "g1f3" if ply == 3 else "b8c6",
        best_move="e2e4" if ply == 1 else "e7e5",
        pv_san_1=san,
    )


def _make_sf_analysis(game, with_derived=True):
    """Create a GameAnalysis with 4 MoveAnalysis rows for the given game.

    Parameters:
        game (Game): The parent game instance.
        with_derived (bool): If True, populate move_win_delta and cpl on every
            row (new-schema). If False, leave them NULL (legacy).

    Returns:
        GameAnalysis: The saved analysis with child moves.
    """
    from analysis.models import GameAnalysis, MoveAnalysis  # deferred import
    ga = GameAnalysis.objects.create(
        game=game,
        analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        engine_depth=20,
        white_accuracy=85.0,
        black_accuracy=82.0,
        white_acpl=18.5,
        black_acpl=22.3,
        white_blunders=0,
        white_mistakes=1,
        white_inaccuracies=2,
        black_blunders=1,
        black_mistakes=1,
        black_inaccuracies=2,
    )
    moves_data = [
        # (ply, san, cp_eval, move_win_delta, cpl, classification)
        (1, "e4",  30.0,  -5.0,   5.0,  "best"),
        (2, "e5",  -25.0, -3.0,   3.0,  "best"),
        (3, "Nf3",  40.0, -2.0,   2.0,  "great"),
        (4, "Nc6", -35.0, -8.0,   8.0,  "inaccuracy"),
    ]
    for ply, san, cp_eval, mwd, cpl_val, cls in moves_data:
        MoveAnalysis.objects.create(
            analysis=ga,
            ply=ply,
            san=san,
            fen=_FENS[ply] if ply < len(_FENS) else _FENS[-1],
            cp_eval=cp_eval,
            mate_in=None,
            cpl=cpl_val if with_derived else None,
            move_win_delta=mwd if with_derived else None,
            classification=cls if with_derived else None,
            arrow_uci_1="e2e4" if ply == 1 else "e7e5" if ply == 2 else "g1f3" if ply == 3 else "b8c6",
            best_move="e2e4" if ply == 1 else "e7e5",
            pv_san_1=san,
        )
    return ga


def _make_lc0_analysis(game, with_derived=True):
    """Create a Lc0GameAnalysis with 4 Lc0MoveAnalysis rows for the given game.

    Parameters:
        game (Game): The parent game instance.
        with_derived (bool): If True, populate wdl_win_adj and related derived
            fields on every row (new-schema). If False, leave them NULL (legacy).

    Returns:
        Lc0GameAnalysis: The saved analysis with child moves.
    """
    from analysis.models import Lc0GameAnalysis, Lc0MoveAnalysis  # deferred import
    lga = Lc0GameAnalysis.objects.create(
        game=game,
        analyzed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        engine_nodes=800,
        network_name="BT4-1024x15x32h-swa-6147500",
        white_win_prob=0.58,
        white_draw_prob=0.30,
        white_loss_prob=0.12,
        black_win_prob=0.42,
        black_draw_prob=0.30,
        black_loss_prob=0.28,
        draw_rate_reference=0.30,
        wdl_calibration_elo=1500,
        contempt=0,
        white_accuracy=87.5,
        black_accuracy=84.2,
    )
    moves_data = [
        # (ply, san, wdl_win_adj, wdl_draw_adj, wdl_loss_adj, wdl_mu, delta_mu, base_sev, draw_char)
        (1, "e4",  530, 290, 180,  0.669, -0.031, "best",       "balanced"),
        (2, "e5",  470, 310, 220,  0.625,  0.044, "best",       "balanced"),
        (3, "Nf3", 545, 285, 170,  0.683, -0.058, "great",      "sharp"),
        (4, "Nc6", 460, 315, 225,  0.618,  0.065, "inaccuracy", "drawish"),
    ]
    for ply, san, win_adj, draw_adj, loss_adj, mu, dmu, base_sev, draw_char in moves_data:
        if with_derived:
            _make_lc0_move_row(lga, ply, san, win_adj, draw_adj, loss_adj, mu, dmu, base_sev, draw_char)
        else:
            Lc0MoveAnalysis.objects.create(
                analysis=lga,
                ply=ply,
                san=san,
                fen=_FENS[ply] if ply < len(_FENS) else _FENS[-1],
                wdl_win=win_adj,
                wdl_draw=draw_adj,
                wdl_loss=loss_adj,
                wdl_win_adj=None,
                wdl_draw_adj=None,
                wdl_loss_adj=None,
                wdl_mu=None,
                delta_mu=None,
                delta_d=None,
                base_severity=None,
                draw_character=None,
                arrow_uci_1="e2e4" if ply == 1 else "e7e5" if ply == 2 else "g1f3" if ply == 3 else "b8c6",
                best_move="e2e4" if ply == 1 else "e7e5",
                pv_san_1=san,
            )
    return lga


@pytest.fixture
def legacy_game_factory():
    """Return a factory that creates a Game with legacy (pre-derived) SF+LC0 analyses.

    Both SF moves lack move_win_delta and LC0 moves lack wdl_win_adj, so
    get_game_analysis_v2 must return None for such a game.

    Returns:
        Callable[[], Game]: A zero-argument factory producing a unique legacy game.
    """
    def _factory():
        game = _make_game()
        _make_sf_analysis(game, with_derived=False)
        _make_lc0_analysis(game, with_derived=False)
        return game
    return _factory


@pytest.fixture
def legacy_sf_game_factory():
    """Return a factory that creates a Game with legacy SF analysis (no LC0).

    SF MoveAnalysis rows have NULL move_win_delta. Used by
    test_drop_legacy_analyses to verify that legacy rows are deleted while
    new-schema rows are preserved.

    Returns:
        Callable[[], Game]: A zero-argument factory producing a unique legacy SF game.
    """
    def _factory():
        game = _make_game()
        _make_sf_analysis(game, with_derived=False)
        return game
    return _factory


@pytest.fixture
def new_schema_game_factory():
    """Return a factory that creates a Game with fully derived SF+LC0 analyses.

    All MoveAnalysis rows have non-null move_win_delta; all Lc0MoveAnalysis
    rows have non-null wdl_win_adj and all derived LC0 columns populated.
    Produces 4 moves per engine — enough for card, chart, chip, and arrow tests.

    Returns:
        Callable[[], Game]: A zero-argument factory producing a unique new-schema game.
    """
    def _factory():
        game = _make_game()
        _make_sf_analysis(game, with_derived=True)
        _make_lc0_analysis(game, with_derived=True)
        return game
    return _factory


@pytest.fixture
def simple_pgn_game():
    """Return a Game instance backed by the 4-ply test PGN.

    Used by board_builder alignment tests that need a real Game slug.

    Returns:
        Game: Saved game with _SIMPLE_PGN content and no analysis.
    """
    return _make_game()
