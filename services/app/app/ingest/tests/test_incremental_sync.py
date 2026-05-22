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
from unittest.mock import MagicMock, patch

from app.ingest.sync_service import ChessComSyncService, SyncStats


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


def _service_with_limit(month_limit: int) -> ChessComSyncService:
    """Build a service shell with a stubbed settings object (no DB/network)."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    service._settings = MagicMock(ingest_month_limit=month_limit)
    return service


_ALL_ARCHIVES = [f"{_BASE}/2024/04", f"{_BASE}/2024/05", f"{_BASE}/2024/06", f"{_BASE}/2024/07"]


def test_syncstats_archives_skipped_defaults_zero() -> None:
    """SyncStats grows an archives_skipped field defaulting to 0."""
    assert SyncStats(username="x").archives_skipped == 0


def test_select_archives_watermark_drops_older_months() -> None:
    """With a watermark, months before the watermark month are skipped."""
    service = _service_with_limit(24)
    fetched, skipped = service._select_archives(
        _ALL_ARCHIVES, datetime(2024, 6, 1, tzinfo=UTC), full=False
    )
    assert fetched == [f"{_BASE}/2024/06", f"{_BASE}/2024/07"]
    assert skipped == 2


def test_select_archives_full_ignores_watermark() -> None:
    """full=True ignores the watermark and uses the month-limit scope."""
    service = _service_with_limit(0)  # 0 = unlimited in _archive_in_scope
    fetched, skipped = service._select_archives(
        _ALL_ARCHIVES, datetime(2024, 6, 1, tzinfo=UTC), full=True
    )
    assert fetched == _ALL_ARCHIVES
    assert skipped == 0


def test_select_archives_no_watermark_uses_month_limit() -> None:
    """A new player (no watermark) falls back to the month-limit scope."""
    service = _service_with_limit(0)
    fetched, skipped = service._select_archives(_ALL_ARCHIVES, None, full=False)
    assert fetched == _ALL_ARCHIVES
    assert skipped == 0


def _session_cm(session: MagicMock) -> MagicMock:
    """Wrap a mock session in a context manager mock for `with get_session()`."""
    cm = MagicMock()
    cm.__enter__.return_value = session
    cm.__exit__.return_value = False
    return cm


def test_sync_player_skips_archives_older_than_watermark() -> None:
    """Archives before the watermark month are never fetched over HTTP."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    service._settings = MagicMock(ingest_month_limit=24)
    client = MagicMock()
    client.get_archives.return_value = [f"{_BASE}/2024/05", f"{_BASE}/2024/06"]
    client.get_games_for_archive.return_value = []
    service._client = client

    session = MagicMock()
    session.scalar.return_value = MagicMock(id=1)  # player lookup

    with patch("app.ingest.sync_service.get_session", return_value=_session_cm(session)), \
         patch.object(
             ChessComSyncService, "_player_watermark",
             return_value=datetime(2024, 6, 10, tzinfo=UTC),
         ):
        stats = service.sync_player("alice")

    fetched = [call.args[0] for call in client.get_games_for_archive.call_args_list]
    assert fetched == [f"{_BASE}/2024/06"]
    assert stats.archives_skipped == 1
    assert stats.archives_scanned == 1


def test_sync_player_skips_already_loaded_games_in_watermark_month() -> None:
    """Within a fetched archive, games at/below the watermark are not upserted."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    service._settings = MagicMock(ingest_month_limit=24)
    watermark = datetime(2024, 6, 10, tzinfo=UTC)
    wm_epoch = int(watermark.timestamp())
    old_game = {"end_time": wm_epoch - 100}
    new_game = {"end_time": wm_epoch + 100}
    client = MagicMock()
    client.get_archives.return_value = [f"{_BASE}/2024/06"]
    client.get_games_for_archive.return_value = [old_game, new_game]
    service._client = client

    session = MagicMock()
    session.scalar.return_value = MagicMock(id=1)
    upserted: list[dict] = []

    def fake_upsert(_session, _player, payload):
        upserted.append(payload)
        return "inserted"

    with patch("app.ingest.sync_service.get_session", return_value=_session_cm(session)), \
         patch.object(ChessComSyncService, "_player_watermark", return_value=watermark), \
         patch.object(ChessComSyncService, "_upsert_game", side_effect=fake_upsert):
        stats = service.sync_player("alice")

    assert upserted == [new_game]
    assert stats.inserted == 1


def test_sync_player_full_bypasses_watermark() -> None:
    """full=True ignores the watermark: all in-scope games are upserted."""
    service = ChessComSyncService.__new__(ChessComSyncService)
    service._settings = MagicMock(ingest_month_limit=0)  # unlimited scope
    client = MagicMock()
    client.get_archives.return_value = [f"{_BASE}/2024/06"]
    client.get_games_for_archive.return_value = [{"end_time": 1}, {"end_time": 2}]
    service._client = client

    session = MagicMock()
    session.scalar.return_value = MagicMock(id=1)
    upserted: list[dict] = []

    def fake_upsert(_session, _player, payload):
        upserted.append(payload)
        return "inserted"

    # _player_watermark must NOT be consulted when full=True.
    with patch("app.ingest.sync_service.get_session", return_value=_session_cm(session)), \
         patch.object(
             ChessComSyncService, "_player_watermark",
             side_effect=AssertionError("watermark must not be queried when full"),
         ), \
         patch.object(ChessComSyncService, "_upsert_game", side_effect=fake_upsert):
        stats = service.sync_player("alice", full=True)

    assert len(upserted) == 2
    assert stats.inserted == 2


def test_run_sync_passes_full_flag(monkeypatch) -> None:
    """run_sync.py --full reaches sync_player as full=True."""
    import sys

    import app.ingest.run_sync as run_sync

    calls: list[tuple[str, bool]] = []

    def fake_sync_player(_self, username, progress_callback=None, *, full=False):
        calls.append((username, full))
        return SyncStats(username=username)

    monkeypatch.setattr(ChessComSyncService, "__init__", lambda self: None)
    monkeypatch.setattr(ChessComSyncService, "sync_player", fake_sync_player)
    monkeypatch.setattr(
        run_sync, "get_settings", lambda: MagicMock(chess_com_usernames="alice")
    )
    monkeypatch.setattr(sys, "argv", ["run_sync.py", "--usernames", "alice", "--full"])

    run_sync.main()

    assert calls == [("alice", True)]
