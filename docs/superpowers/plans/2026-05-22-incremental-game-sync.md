# Incremental Game Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Chess.com `sync_games` cron fetch and upsert only games newer than what's already loaded, instead of re-pulling up to 24 months of archives every run.

**Architecture:** A per-player watermark (`max(played_at)`) drives two cheap gates in the SQLAlchemy `ChessComSyncService.sync_player`: (1) skip whole archive months older than the watermark month before any HTTP fetch, (2) skip individual games at/below the watermark within fetched archives. A `--full` flag bypasses both for forced re-ingest. The env-driven `ingest_month_limit` becomes the first-sync backfill depth for players with no games yet.

**Tech Stack:** Python 3.13, SQLAlchemy (ingest service), Django management command (cron entrypoint), pytest, `python-chess`.

**Spec:** `docs/superpowers/specs/2026-05-22-incremental-game-sync-design.md`

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `services/app/app/ingest/sync_service.py` | Chess.com fetch + upsert (SQLAlchemy) | Add watermark helpers, archive/game gates, `full` kwarg, `archives_skipped` stat |
| `services/app/app/ingest/run_sync.py` | CLI subprocess entrypoint | Add `--full` flag; report `skipped` in summary |
| `services/app/ingest/management/commands/sync_games.py` | Django cron command | Remove dead `--days`; add `--full` threaded to subprocess |
| `services/app/app/ingest/tests/test_incremental_sync.py` | Unit + integration tests (no DB) | **Create** |
| `services/app/ingest/tests/test_sync_games_command.py` | Command tests (Django DB) | Add `--full` passthrough tests |

**Two ORMs, deliberately:** the Django command (`sync_games.py`) uses Django models; the subprocess it shells out to (`run_sync.py` → `sync_service.py`) uses SQLAlchemy. All watermark logic lives in the SQLAlchemy `sync_service.py`. Do **not** touch the stale duplicate copies under `packages/shared/wood_league_shared/ingest/` or `services/stockfish_worker/stockfish_pipeline/ingest/` — they are not on the cron path.

**Observability note (deviation from spec §5):** `archives_skipped` is surfaced in `run_sync.py`'s printed summary, which streams to the cron logs (the command runs the subprocess with `capture_output=False`, so its stdout is inherited by the Railway cron log). It is **not** added to the Django `SystemEvent.details`, because the command intentionally does not capture subprocess output (it streams the live progress bar). Feeding subprocess stats back into `SystemEvent` would require capturing/parsing that stream and is out of scope.

**Test commands.** All commands run from `services/app/`. Use the repo-root venv by absolute path:

```bash
PYBIN=/Users/christopherwebster/Projects/wood_league/.venv/bin/python
```

Pure/unit and mock-based integration tests (`test_incremental_sync.py`) need no database. The command tests (`test_sync_games_command.py`) are Django `TestCase`s and use the test DB configured via `services/app/.env.test` (`TEST_DATABASE_URL`).

---

## Task 1: Watermark epoch + per-game freshness helpers

Two pure static helpers on `ChessComSyncService`: `_to_epoch` (normalizes a possibly-naive UTC datetime to an int Unix epoch) and `_payload_is_new` (decides whether a game payload is at/after the watermark).

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py` (create)
- Modify: `services/app/app/ingest/sync_service.py`

- [ ] **Step 1: Write the failing tests**

Create `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_to_epoch'`.

- [ ] **Step 3: Add the helpers**

In `services/app/app/ingest/sync_service.py`, add these two static methods to the `ChessComSyncService` class (place them just after `_archive_in_scope`):

```python
    @staticmethod
    def _to_epoch(moment: datetime) -> int:
        """Convert a datetime to an integer Unix epoch, treating naive as UTC.

        Args:
            moment: A datetime. If naive (no tzinfo) it is interpreted as UTC,
                matching how Game.played_at is stored.

        Returns:
            int: Seconds since the Unix epoch.
        """
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return int(moment.timestamp())

    @staticmethod
    def _payload_is_new(payload: dict, watermark_epoch: int) -> bool:
        """Return True if a game payload ends at or after the watermark epoch.

        Args:
            payload: A Chess.com game payload (uses its integer 'end_time').
            watermark_epoch: The player's latest loaded game time as Unix epoch.

        Returns:
            bool: True when end_time >= watermark_epoch (process it); False when
            strictly older (already loaded — skip). The boundary case is treated
            as new so a genuinely new game sharing the watermark's exact second
            is never dropped.
        """
        return int(payload.get("end_time", 0)) >= watermark_epoch
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/tests/test_incremental_sync.py services/app/app/ingest/sync_service.py
git commit -m "feat(#204): add watermark epoch + per-game freshness helpers

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Archive month gate

A pure static helper that decides whether an archive URL's `YYYY/MM` is at or after the watermark's month.

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py`
- Modify: `services/app/app/ingest/sync_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_archive_in_watermark_scope'`.

- [ ] **Step 3: Add the helper**

In `services/app/app/ingest/sync_service.py`, add this static method to `ChessComSyncService` (place it right after `_archive_in_scope`):

```python
    @staticmethod
    def _archive_in_watermark_scope(archive_url: str, watermark: datetime) -> bool:
        """Return True if the archive's year/month is >= the watermark's month.

        Chess.com archive URLs end with '/YYYY/MM'. Any archive whose month is
        strictly before the watermark's month contains only already-loaded
        games and can be skipped without an HTTP fetch.

        Args:
            archive_url: A Chess.com monthly archive URL.
            watermark: The player's latest loaded game datetime (UTC).

        Returns:
            bool: True to fetch the archive; False to skip it. Unparseable URLs
            return True (fetch) so a parsing quirk never drops real games.
        """
        parts = archive_url.rstrip("/").split("/")
        if len(parts) < 2:
            return True
        try:
            year = int(parts[-2])
            month = int(parts[-1])
        except ValueError:
            return True
        return (year, month) >= (watermark.year, watermark.month)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/tests/test_incremental_sync.py services/app/app/ingest/sync_service.py
git commit -m "feat(#204): add archive month gate for watermark scope

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Player watermark query

An instance method that returns the player's latest `played_at` via the `GameParticipant` join, or `None` when the player has no games.

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py`
- Modify: `services/app/app/ingest/sync_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: FAIL — `AttributeError: ... has no attribute '_player_watermark'`.

- [ ] **Step 3: Add the method and import `func`**

In `services/app/app/ingest/sync_service.py`, change the SQLAlchemy import:

```python
from sqlalchemy import select
```

to:

```python
from sqlalchemy import func, select
```

(`Game`, `GameParticipant`, and `Player` are already imported on the existing `from app.storage.models import ...` line — no change there.)

Then add this method to `ChessComSyncService` (place it right after `_archive_in_watermark_scope`):

```python
    def _player_watermark(self, session, player) -> datetime | None:
        """Return the player's latest game time, or None if they have no games.

        Args:
            session: An active SQLAlchemy session.
            player: The Player whose games define the watermark.

        Returns:
            datetime | None: max(Game.played_at) over games this player took
            part in (joined via GameParticipant), or None when there are none.
        """
        return session.scalar(
            select(func.max(Game.played_at))
            .join(GameParticipant, GameParticipant.game_id == Game.id)
            .where(GameParticipant.player_id == player.id)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: PASS (12 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/sync_service.py services/app/app/ingest/tests/test_incremental_sync.py
git commit -m "feat(#204): add per-player played_at watermark query

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `archives_skipped` stat + archive selection

Add an `archives_skipped` counter to `SyncStats` and an instance method `_select_archives` that returns `(archives_to_fetch, skipped_count)`, applying the watermark month gate when a watermark exists and not `full`, else the existing `ingest_month_limit` scope.

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py`
- Modify: `services/app/app/ingest/sync_service.py`

- [ ] **Step 1: Write the failing tests**

Append to `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: FAIL — `AttributeError` on `archives_skipped` / `_select_archives`.

- [ ] **Step 3: Add the field and method**

In `services/app/app/ingest/sync_service.py`, add the field to the `SyncStats` dataclass:

```python
@dataclass
class SyncStats:
    """Statistics from syncing a single player's Chess.com archives."""
    username: str
    inserted: int = 0
    updated: int = 0
    archives_scanned: int = 0
    archives_skipped: int = 0
```

Then add this method to `ChessComSyncService` (place it right after `_player_watermark`):

```python
    def _select_archives(
        self, all_archives: list[str], watermark: datetime | None, full: bool
    ) -> tuple[list[str], int]:
        """Choose which archives to fetch and count how many are skipped.

        When the player has a watermark and full is False, only archives at or
        after the watermark's month are fetched (older months hold only
        already-loaded games). Otherwise the existing ingest_month_limit scope
        applies — the first-sync backfill depth for new players, and the full
        re-ingest scope when full is True.

        Args:
            all_archives: Every archive URL Chess.com returned for the player.
            watermark: The player's latest game datetime, or None.
            full: When True, ignore the watermark and use the month-limit scope.

        Returns:
            tuple[list[str], int]: (archives to fetch, count skipped).
        """
        if watermark is not None and not full:
            fetched = [
                url for url in all_archives
                if self._archive_in_watermark_scope(url, watermark)
            ]
        else:
            fetched = [url for url in all_archives if self._archive_in_scope(url)]
        return fetched, len(all_archives) - len(fetched)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/sync_service.py services/app/app/ingest/tests/test_incremental_sync.py
git commit -m "feat(#204): add archives_skipped stat and watermark archive selection

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire the watermark into `sync_player`

Rewrite `sync_player` to compute the watermark, select archives, and skip already-loaded games — gated by a new `full` kwarg. Two mock-based integration tests prove old archives aren't fetched and already-loaded games aren't upserted.

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py`
- Modify: `services/app/app/ingest/sync_service.py` (`sync_player`)

- [ ] **Step 1: Write the failing tests**

Append to `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: FAIL — `sync_player()` has no `full` kwarg / old archive still fetched.

- [ ] **Step 3: Rewrite `sync_player`**

In `services/app/app/ingest/sync_service.py`, replace the entire `sync_player` method with:

```python
    def sync_player(
        self,
        username: str,
        progress_callback: SyncProgressCallback | None = None,
        *,
        full: bool = False,
    ) -> SyncStats:
        """Sync a player's new games, skipping archives/games already loaded.

        A per-player watermark (max played_at) gates the work: archive months
        older than the watermark are not fetched, and games at/below the
        watermark within fetched archives are not upserted. Pass full=True to
        ignore the watermark and re-ingest every archive within the configured
        ingest_month_limit (used for forced re-syncs and the first sync of a
        player with no games yet).

        Args:
            username: Chess.com username to sync.
            progress_callback: Optional callback (username, idx, total, stats).
            full: When True, bypass the watermark and re-ingest all in-scope
                archives.

        Returns:
            SyncStats: Per-player counts (inserted, updated, archives scanned
            and skipped).
        """
        username = username.lower().strip()
        stats = SyncStats(username=username)

        with get_session() as session:
            player = session.scalar(select(Player).where(Player.username == username))
            if player is None:
                player = Player(username=username, display_name=username)
                session.add(player)
                session.flush()

            watermark = None if full else self._player_watermark(session, player)
            all_archives = self._client.get_archives(username)
            archives, stats.archives_skipped = self._select_archives(
                all_archives, watermark, full
            )
            stats.archives_scanned = len(archives)
            watermark_epoch = self._to_epoch(watermark) if watermark is not None else None

            if progress_callback is not None:
                progress_callback(username, 0, len(archives), stats)

            for archive_idx, archive_url in enumerate(archives, start=1):
                for payload in self._client.get_games_for_archive(archive_url):
                    if watermark_epoch is not None and not self._payload_is_new(
                        payload, watermark_epoch
                    ):
                        continue
                    changed = self._upsert_game(session, player, payload)
                    if changed == "inserted":
                        stats.inserted += 1
                    elif changed == "updated":
                        stats.updated += 1

                if progress_callback is not None:
                    progress_callback(username, archive_idx, len(archives), stats)

            session.commit()

        return stats
```

Also update the `sync_service.py` file-header changelog: add a line under `Changelog:`:

```
    2026-05-22: Incremental sync (#204) — per-player played_at watermark skips
                archive months and games already loaded; full= forces re-ingest.
```

- [ ] **Step 4: Run the new tests, then the whole ingest unit suite**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/ -q`
Expected: PASS (existing `test_upsert_game_empty_pgn.py` 7 tests + new `test_incremental_sync.py` 19 tests).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/sync_service.py services/app/app/ingest/tests/test_incremental_sync.py
git commit -m "feat(#204): wire per-player watermark into sync_player

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `--full` flag in the CLI subprocess

Add a `--full` flag to `run_sync.py`, pass it through to `sync_player`, and include `skipped` in the per-player summary so the saving is visible in cron logs.

**Files:**
- Test: `services/app/app/ingest/tests/test_incremental_sync.py`
- Modify: `services/app/app/ingest/run_sync.py`

- [ ] **Step 1: Write the failing test**

Append to `services/app/app/ingest/tests/test_incremental_sync.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py::test_run_sync_passes_full_flag -q`
Expected: FAIL — `--full` is an unrecognized argument (SystemExit from argparse).

- [ ] **Step 3: Add the flag and pass it through**

In `services/app/app/ingest/run_sync.py`, add the argument after the existing `--usernames` argument:

```python
    parser.add_argument(
        "--full",
        action="store_true",
        help="Ignore the per-player watermark and re-ingest all in-scope archives.",
    )
```

Change the `sync_player` call from:

```python
        result = service.sync_player(username, progress_callback=progress_callback)
```

to:

```python
        result = service.sync_player(
            username, progress_callback=progress_callback, full=args.full
        )
```

Change the summary print from:

```python
        print(
            f"{result.username}: archives={result.archives_scanned} inserted={result.inserted} updated={result.updated}"
        )
```

to:

```python
        print(
            f"{result.username}: archives={result.archives_scanned} "
            f"skipped={result.archives_skipped} "
            f"inserted={result.inserted} updated={result.updated}"
        )
```

Also add to the `run_sync.py` file-header changelog:

```
    2026-05-22: Add --full to bypass the incremental watermark (#204) and
                report archives skipped in the summary.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd services/app && $PYBIN -m pytest app/ingest/tests/test_incremental_sync.py -q`
Expected: PASS (20 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/app/ingest/run_sync.py services/app/app/ingest/tests/test_incremental_sync.py
git commit -m "feat(#204): add --full flag and skipped count to run_sync CLI

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: `sync_games` command — drop dead `--days`, add `--full`

Remove the unwired `--days` argument (it would crash `run_sync.py` if ever set) and add `--full`, threaded into the subprocess command.

**Files:**
- Test: `services/app/ingest/tests/test_sync_games_command.py`
- Modify: `services/app/ingest/management/commands/sync_games.py`

- [ ] **Step 1: Write the failing tests**

Append two methods inside the `SyncGamesCommandTests` class in `services/app/ingest/tests/test_sync_games_command.py`:

```python
    def test_full_flag_passed_to_subprocess(self):
        """--full must be forwarded to the run_sync.py subprocess command."""
        suffix = uuid.uuid4().hex[:6]
        _make_player(f"alice-{suffix}")
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args[0] if args else kwargs.get("args")
            return MagicMock(returncode=0)

        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            call_command("sync_games", f"alice-{suffix}", "--full", stdout=StringIO())

        assert "--full" in captured["args"], captured["args"]

    def test_full_flag_absent_by_default(self):
        """Without --full the subprocess command must not contain it."""
        suffix = uuid.uuid4().hex[:6]
        _make_player(f"alice-{suffix}")
        captured = {}

        def fake_run(*args, **kwargs):
            captured["args"] = args[0] if args else kwargs.get("args")
            return MagicMock(returncode=0)

        with patch(
            "ingest.management.commands.sync_games.subprocess.run",
            side_effect=fake_run,
        ):
            call_command("sync_games", f"alice-{suffix}", stdout=StringIO())

        assert "--full" not in captured["args"], captured["args"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/app && $PYBIN -m pytest ingest/tests/test_sync_games_command.py::SyncGamesCommandTests::test_full_flag_passed_to_subprocess -q`
Expected: FAIL — argparse rejects the unknown `--full` option (CommandError / SystemExit).

- [ ] **Step 3: Update the command**

In `services/app/ingest/management/commands/sync_games.py`, in `add_arguments`, replace the `--days` block:

```python
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Only sync archives from the last N days.",
        )
```

with:

```python
        parser.add_argument(
            "--full",
            action="store_true",
            help=(
                "Ignore the per-player watermark and re-ingest all in-scope "
                "archives (forced full re-sync)."
            ),
        )
```

In `_do_sync`, replace the subprocess command assembly:

```python
        cmd = [sys.executable, str(_SCRIPT), "--usernames", ",".join(usernames)]
        if options["days"]:
            cmd += ["--days", str(options["days"])]
```

with:

```python
        cmd = [sys.executable, str(_SCRIPT), "--usernames", ",".join(usernames)]
        if options["full"]:
            cmd += ["--full"]
```

Also add to the `sync_games.py` file-header changelog:

```
    2026-05-22: Drop dead --days; add --full to force full re-ingest (#204).
```

- [ ] **Step 4: Run the command tests to verify they pass**

Run: `cd services/app && $PYBIN -m pytest ingest/tests/test_sync_games_command.py -q`
Expected: PASS (5 existing + 2 new = 7 passed).

- [ ] **Step 5: Commit**

```bash
git add services/app/ingest/management/commands/sync_games.py services/app/ingest/tests/test_sync_games_command.py
git commit -m "feat(#204): sync_games drops dead --days, adds --full passthrough

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Full verification + wiki note

Run the full affected suites, bandit on edited Python files, and add a brief note to the ingest wiki page describing incremental sync.

**Files:**
- Modify: `wood_league.wiki/Game-Ingest-Process.md`

- [ ] **Step 1: Run the full affected test suites**

Run:
```bash
cd services/app && $PYBIN -m pytest app/ingest/tests/ ingest/tests/test_sync_games_command.py -q
```
Expected: PASS (20 + 7 = 27 passed, 0 failures).

- [ ] **Step 2: Run bandit on the edited Python files**

Run:
```bash
cd services/app && $PYBIN -m bandit -ll app/ingest/sync_service.py app/ingest/run_sync.py ingest/management/commands/sync_games.py
```
Expected: No Medium/High issues. (`subprocess` use in `sync_games.py` already carries a `# noqa: S603` and is pre-existing; bandit `-ll` should report nothing new.)

- [ ] **Step 3: Add the wiki note**

In `wood_league.wiki/Game-Ingest-Process.md`, find the line:

```
Optionally, ingest can be limited to recent archives via the `ingest_month_limit` setting. Games older than this are skipped.
```

and add immediately after it:

```
Ingest is also incremental: each run records the newest game already saved for a
player and skips archive months older than that, plus individual games already
loaded, so the cron only processes genuinely new games. The `ingest_month_limit`
setting therefore bounds only the first sync of a player who has no games yet.
Run the sync with `--full` (`python manage.py sync_games --full`) to ignore this
and re-ingest every in-scope archive — useful after ingest logic changes.
```

- [ ] **Step 4: Commit**

```bash
git add wood_league.wiki/Game-Ingest-Process.md
git commit -m "docs(#204): note incremental sync + --full on ingest wiki page

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- §1 watermark + tz handling → Tasks 1, 3 ✓
- §2 archive month gate (skip whole months, month-limit fallback) → Tasks 2, 4 ✓
- §3 per-game `end_time < watermark` skip (strict `<`) → Tasks 1, 5 ✓
- §4 `--full` end to end + remove dead `--days` → Tasks 6, 7 ✓
- §5 `archives_skipped` observability → Task 4 (stat) + Task 6 (cron-log summary); SystemEvent integration explicitly deferred with rationale in File Structure notes ✓
- §6 testing matrix → Tasks 1-7 cover every listed case ✓
- Edge cases (new member, corrected game, empty PGN, same-second boundary) → covered by `full` fallback, strict `<`, and untouched `_upsert_game` #18 guard ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `_to_epoch(datetime)->int`, `_payload_is_new(dict,int)->bool`, `_archive_in_watermark_scope(str,datetime)->bool`, `_player_watermark(session,player)->datetime|None`, `_select_archives(list,datetime|None,bool)->tuple[list,int]`, `sync_player(..., *, full=False)->SyncStats`, `SyncStats.archives_skipped:int`. Names/signatures match across tasks and the test calls. ✓
