"""
Title: test_upsert_game_empty_pgn.py — Empty-PGN drop on Chess.com ingest
Description:
    Verifies that ``ChessComSyncService._upsert_game`` drops payloads whose PGN
    has no mainline moves (abandoned games, forfeits, sync glitches) so they
    never reach the database and therefore can't trigger 0-ply auto-enqueued
    analyses (issue #18).

Changelog:
    2026-05-11: Initial — issue #18 ingest-side guard.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ingest.sync_service import ChessComSyncService


@pytest.mark.parametrize(
    ("pgn", "expected"),
    [
        ("", False),
        ("   \n", False),
        # PGN headers only, no mainline moves — what Chess.com returns for some
        # abandoned/forfeit games.
        ('[Event "Live Chess"]\n[Result "1-0"]\n\n*', False),
        # Well-formed minimal PGN with one move.
        ('[Event "Live Chess"]\n\n1. e4 *', True),
        # Bare moves without headers.
        ("1. e4 e5 2. Nf3 *", True),
    ],
)
def test_has_mainline_moves(pgn: str, expected: bool) -> None:
    """``_has_mainline_moves`` distinguishes move-bearing PGNs from empty/glitched ones."""
    assert ChessComSyncService._has_mainline_moves(pgn) is expected


def test_upsert_game_skips_empty_pgn_payload() -> None:
    """An empty-PGN payload must NOT create a Game row and must return 'skipped'.

    This is the key acceptance criterion for issue #18: such rows used to be
    inserted and then auto-enqueued for analysis, producing all-zero
    GameAnalysis stats. With the guard in place the row is never written, so
    downstream auto-enqueue scans (``Game.objects.filter(created_at__gte=...)``)
    never see them.
    """
    service = ChessComSyncService.__new__(ChessComSyncService)
    session = MagicMock(name="session")
    player = MagicMock(name="player", username="alice")
    payload = {
        "uuid": "abandoned-game-id",
        "white": {"username": "alice"},
        "black": {"username": "bob"},
        "pgn": '[Event "Live Chess"]\n[Result "0-1"]\n\n*',
        "end_time": 1_700_000_000,
        "time_control": "600",
    }

    result = service._upsert_game(session, player, payload)

    assert result == "skipped"
    session.add.assert_not_called()
    session.get.assert_not_called()


def test_upsert_game_keeps_payload_with_moves() -> None:
    """A payload with at least one mainline move must NOT be skipped.

    Guards against an over-eager filter that drops legitimate games. We stub
    out the heavier helpers — this test only proves the move-bearing payload
    takes the non-skipped code path.
    """
    service = ChessComSyncService.__new__(ChessComSyncService)
    session = MagicMock(name="session")
    session.get.return_value = None  # force "inserted" path
    session.scalar.return_value = None  # no existing slug, no existing participant
    session.scalars.return_value.all.return_value = []
    player = MagicMock(name="player", username="alice", id=1)
    payload = {
        "uuid": "real-game-id",
        "white": {"username": "alice", "rating": 1500, "result": "win"},
        "black": {"username": "bob", "rating": 1480, "result": "checkmated"},
        "pgn": '[Event "Live Chess"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 1-0',
        "end_time": 1_700_000_000,
        "start_time": 1_700_000_000 - 600,
        "time_control": "600",
        "time_class": "rapid",
    }

    with patch.object(ChessComSyncService, "_lichess_opening_from_pgn", return_value=None):
        result = service._upsert_game(session, player, payload)

    assert result == "inserted"
    assert session.add.called  # Game row added to session
