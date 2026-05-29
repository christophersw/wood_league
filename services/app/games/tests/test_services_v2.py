"""
Title: test_services_v2.py — Tests for the new-schema-only analysis loader
Description:
    Verifies that get_game_analysis_v2 returns None for missing games,
    None for legacy (pre-derived-fields) games, and a fully populated
    GameAnalysisDataV2 for games with the new schema fields present.

Changelog:
    2026-05-21 (#186): Initial.
    2026-05-29 (#226): Tests for time_control_label, opening_book_id,
                       opening_common_name, book_ply_count, winner_username,
                       white_is_winner, and black_is_winner.
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


@pytest.mark.django_db
def test_new_fields_time_control_label_and_book_context(monkeypatch):
    """GameAnalysisDataV2 carries TC label, book context, and winner fields (#226).

    Creates a rapid game (600+5) whose white player is the winner, patches
    lookup_opening_entry to return a scripted sequence so no real opening DB
    rows are needed, and asserts:
      - time_control_label == "Rapid · 10+5 min"
      - opening_book_id is not None
      - opening_common_name is non-empty
      - book_ply_count >= 2
      - winner_username matches white_username
      - white_is_winner is True, black_is_winner is False
    """
    from datetime import datetime, timezone
    from uuid import uuid4
    from games.models import Game
    from games.tests.conftest import _make_sf_analysis, _make_lc0_analysis

    slug = uuid4().hex[:12]
    pgn = (
        '[Event "Test"]\n'
        '[Site "?"]\n'
        '[Date "2026.01.01"]\n'
        '[Round "1"]\n'
        '[White "Alice"]\n'
        '[Black "Bob"]\n'
        '[Result "1-0"]\n'
        '[TimeControl "600+5"]\n'
        "\n"
        "1. e4 e5 2. Nf3 Nc6 *"
    )
    game = Game.objects.create(
        id=slug,
        slug=slug,
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="600+5",
        time_class="rapid",
        white_username="Alice",
        black_username="Bob",
        white_rating=1500,
        black_rating=1500,
        result_pgn="1-0",
        winner_username="Alice",
        pgn=pgn,
    )
    _make_sf_analysis(game, with_derived=True)
    _make_lc0_analysis(game, with_derived=True)

    # Script the opening-book walk:
    # start pos hit, ply-1 hit, ply-2 hit (deepest), ply-3 → None (exits book)
    call_count = {"n": 0}
    sequence = [
        (10, "C40", "King's Knight Opening"),  # start
        (10, "C40", "King's Knight Opening"),  # ply 1: 1.e4
        (11, "C41", "Philidor Defense"),        # ply 2: 1...e5 — deepest
        None,                                   # ply 3: 2.Nf3 — exits book
    ]

    def fake_lookup(_board):
        """Return next entry from the scripted sequence."""
        i = call_count["n"]
        call_count["n"] += 1
        return sequence[i] if i < len(sequence) else None

    monkeypatch.setattr("games.opening_book_context.lookup_opening_entry", fake_lookup)

    data = get_game_analysis_v2(game.slug)
    assert data is not None
    assert data.time_control_label == "Rapid · 10+5 min"
    assert data.opening_book_id is not None
    assert data.opening_common_name != ""
    assert data.book_ply_count >= 2
    assert data.winner_username == "Alice"
    assert data.white_is_winner is True
    assert data.black_is_winner is False


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
