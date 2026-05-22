"""
Title: test_incremental_sync.py — Watermark-driven incremental sync (#204)
Description:
    Unit and mock-based integration tests for the per-player watermark that
    makes ChessComSyncService.sync_player fetch and upsert only games newer
    than those already loaded. Covers the pure decision helpers, the archive
    month gate, the watermark query, archive selection, and the wired-up
    sync_player behaviour. None of these tests touch a real database.

Changelog:
    2026-05-22: Initial — issue #204 incremental game sync.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.ingest.sync_service import ChessComSyncService


def test_to_epoch_naive_treated_as_utc() -> None:
    """A naive datetime is interpreted as UTC, not local time."""
    assert ChessComSyncService._to_epoch(datetime(2024, 1, 1, 0, 0, 0)) == 1_704_067_200


def test_to_epoch_aware_matches_naive() -> None:
    """An aware UTC datetime and the equivalent naive one yield the same epoch."""
    naive = datetime(2024, 1, 1, 0, 0, 0)
    aware = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert ChessComSyncService._to_epoch(naive) == ChessComSyncService._to_epoch(aware)


def test_payload_after_watermark_is_new() -> None:
    """A game ending after the watermark is new and must be processed."""
    assert ChessComSyncService._payload_is_new({"end_time": 200}, 100) is True


def test_payload_at_watermark_is_new() -> None:
    """A game ending exactly at the watermark is treated as new (strict-< skip)."""
    assert ChessComSyncService._payload_is_new({"end_time": 100}, 100) is True


def test_payload_before_watermark_not_new() -> None:
    """A game ending before the watermark is already loaded and is skipped."""
    assert ChessComSyncService._payload_is_new({"end_time": 50}, 100) is False


_WATERMARK = datetime(2024, 6, 15, tzinfo=UTC)
_BASE = "https://api.chess.com/pub/player/alice/games"


def test_archive_newer_month_in_scope() -> None:
    """An archive month after the watermark month is kept."""
    assert ChessComSyncService._archive_in_watermark_scope(f"{_BASE}/2024/07", _WATERMARK) is True


def test_archive_same_month_in_scope() -> None:
    """The watermark's own month is kept (it can hold newer games)."""
    assert ChessComSyncService._archive_in_watermark_scope(f"{_BASE}/2024/06", _WATERMARK) is True


def test_archive_older_month_out_of_scope() -> None:
    """An earlier month in the same year is skipped."""
    assert ChessComSyncService._archive_in_watermark_scope(f"{_BASE}/2024/05", _WATERMARK) is False


def test_archive_older_year_out_of_scope() -> None:
    """An earlier year is skipped."""
    assert ChessComSyncService._archive_in_watermark_scope(f"{_BASE}/2023/12", _WATERMARK) is False


def test_archive_unparseable_defaults_in_scope() -> None:
    """An unparseable URL is fetched rather than silently dropped."""
    assert ChessComSyncService._archive_in_watermark_scope("garbage", _WATERMARK) is True


def test_player_watermark_returns_scalar() -> None:
    """The watermark is whatever the max(played_at) query returns."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    session = MagicMock(name="session")
    expected = datetime(2024, 6, 1, tzinfo=UTC)
    session.scalar.return_value = expected
    assert service._player_watermark(session, MagicMock(id=7)) == expected
    assert session.scalar.called


def test_player_watermark_none_when_no_games() -> None:
    """A player with no games has no watermark."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    session = MagicMock(name="session")
    session.scalar.return_value = None
    assert service._player_watermark(session, MagicMock(id=7)) is None
