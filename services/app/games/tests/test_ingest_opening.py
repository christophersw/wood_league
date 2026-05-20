"""
Title: test_ingest_opening.py
Description: Verifies that the post-sync opening-ID sweep populates
    ``Game.opening_id`` for newly ingested games using
    ``resolve_opening_id``.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from __future__ import annotations

import pytest
from unittest import mock

from games.models import Game
from ingest.management.commands.sync_games import _populate_opening_ids_for_recent_games
from openings.models import OpeningBook


@pytest.mark.django_db
def test_populate_opening_ids_sets_opening_id() -> None:
    """``_populate_opening_ids_for_recent_games`` writes ``opening_id`` on each game.

    The resolver is mocked to return the id of a real OpeningBook row so the
    FK constraint is satisfied. The sweep must call it once per game and persist
    the value.
    """
    import io
    fake_stdout = io.StringIO()

    opening = OpeningBook.objects.create(
        eco="B00",
        name="Test Opening",
        pgn="1. e4",
        epd="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
    )

    Game.objects.create(
        id="test-game-1",
        slug="test-game-1",
        played_at="2026-01-01T00:00:00Z",
        time_control="600",
        pgn="[Event \"t\"]\n[White \"a\"]\n[Black \"b\"]\n[Result \"1-0\"]\n\n1. e4 e5 2. Nf3 *",
    )

    with mock.patch(
        "ingest.management.commands.sync_games.resolve_opening_id",
        return_value=opening.id,
    ):
        count = _populate_opening_ids_for_recent_games(since=None, stdout=fake_stdout)

    assert count == 1
    game = Game.objects.get(id="test-game-1")
    assert game.opening_id == opening.id


@pytest.mark.django_db
def test_populate_opening_ids_skips_empty_pgn() -> None:
    """Games with empty PGN are skipped; resolver is never called.

    Side effect: count stays 0, opening_id stays None.
    """
    import io
    fake_stdout = io.StringIO()

    Game.objects.create(
        id="test-game-2",
        slug="test-game-2",
        played_at="2026-01-01T00:00:00Z",
        time_control="600",
        pgn="",
    )

    with mock.patch(
        "ingest.management.commands.sync_games.resolve_opening_id",
    ) as mock_resolver:
        count = _populate_opening_ids_for_recent_games(since=None, stdout=fake_stdout)

    assert count == 0
    mock_resolver.assert_not_called()


@pytest.mark.django_db
def test_populate_opening_ids_skips_already_resolved() -> None:
    """Games whose ``opening_id`` is already populated are skipped (#168).

    The per-cycle post-step must not re-walk rows that have already been
    resolved. The resolver should be called once for the un-resolved game and
    not for the resolved one.
    """
    import io
    fake_stdout = io.StringIO()

    opening = OpeningBook.objects.create(
        eco="B00",
        name="Test Opening",
        pgn="1. e4",
        epd="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq -",
    )

    # Already-resolved game — must be skipped.
    Game.objects.create(
        id="resolved-game",
        slug="resolved-game",
        played_at="2026-01-01T00:00:00Z",
        time_control="600",
        pgn="[Event \"t\"]\n\n1. e4 *",
        opening_id=opening.id,
    )
    # Unresolved game — must be processed.
    Game.objects.create(
        id="unresolved-game",
        slug="unresolved-game",
        played_at="2026-01-01T00:00:00Z",
        time_control="600",
        pgn="[Event \"t\"]\n\n1. d4 *",
    )

    with mock.patch(
        "ingest.management.commands.sync_games.resolve_opening_id",
        return_value=opening.id,
    ) as mock_resolver:
        count = _populate_opening_ids_for_recent_games(since=None, stdout=fake_stdout)

    assert count == 1
    assert mock_resolver.call_count == 1
    # The already-resolved row is untouched.
    assert Game.objects.get(id="resolved-game").opening_id == opening.id


@pytest.mark.django_db
def test_populate_opening_ids_none_resolver_result() -> None:
    """When resolver returns None the column stays None (not 0 or raising)."""
    import io
    fake_stdout = io.StringIO()

    Game.objects.create(
        id="test-game-3",
        slug="test-game-3",
        played_at="2026-01-01T00:00:00Z",
        time_control="600",
        pgn="[Event \"t\"]\n\n1. d4 *",
    )

    with mock.patch(
        "ingest.management.commands.sync_games.resolve_opening_id",
        return_value=None,
    ):
        count = _populate_opening_ids_for_recent_games(since=None, stdout=fake_stdout)

    assert count == 1  # still processed; just no match
    game = Game.objects.get(id="test-game-3")
    assert game.opening_id is None
