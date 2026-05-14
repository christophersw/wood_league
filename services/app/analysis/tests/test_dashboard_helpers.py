"""
Title: test_dashboard_helpers.py — Unit tests for dashboard helpers
Description:
    Pure-function tests for the dashboard's liveness, uptime, hardware,
    rate, ETA, game-link, and recent-game grouping helpers.

Changelog:
    2026-05-14 (#106): Initial test module.
    2026-05-14 (#106): Cover percentile interpolation, throughput_rows,
        worker-log url matching, and multi-job latest_completed_at update.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from analysis.dashboard_helpers import (
    LIVENESS_HEALTHY_SECONDS,
    LIVENESS_WARNING_SECONDS,
    _engine_throughput_row,
    _eta_for,
    _format_memory_mb,
    _format_uptime,
    _game_link_for,
    _group_recent_by_game,
    _liveness_for,
    _percentile,
    _rate_per_min,
    _throughput_for_window,
    _worker_log_url_for,
)
from analysis.models import AnalysisJob
from games.models import Game


@pytest.mark.parametrize("seconds, expected", [
    (0, "healthy"),
    (59, "healthy"),
    (60, "warning"),
    (119, "warning"),
    (120, "stale"),
    (3600, "stale"),
])
def test_liveness_buckets(seconds, expected):
    """Liveness classification by delta seconds."""
    assert _liveness_for(timedelta(seconds=seconds)) == expected


def test_liveness_none_treated_as_stale():
    """A missing delta (no heartbeat ever) is ``'stale'``."""
    assert _liveness_for(None) == "stale"


def test_liveness_thresholds_are_constants():
    """Thresholds are exported as module-level constants for reuse."""
    assert LIVENESS_HEALTHY_SECONDS == 60
    assert LIVENESS_WARNING_SECONDS == 120


@pytest.mark.parametrize("seconds, expected", [
    (5, "5s"),
    (59, "59s"),
    (60, "1m"),
    (22 * 60 + 30, "22m"),
    (59 * 60 + 59, "59m"),
    (3600, "1h 0m"),
    (3 * 3600 + 12 * 60, "3h 12m"),
    (86400 + 4 * 3600, "1d 4h"),
    (10 * 86400, "10d 0h"),
])
def test_format_uptime_buckets(seconds, expected):
    """Uptime formatting across seconds/minutes/hours/days buckets."""
    assert _format_uptime(timedelta(seconds=seconds)) == expected


def test_format_uptime_none_returns_dash():
    """Missing started_at renders as an em-dash placeholder."""
    assert _format_uptime(None) == "—"


@pytest.mark.parametrize("mb, expected", [
    (62000, "60.5 GB"),
    (1024, "1.0 GB"),
    (512, "512 MB"),
])
def test_format_memory_mb_buckets(mb, expected):
    """Memory formatting in MB and GB."""
    assert _format_memory_mb(mb) == expected


def test_format_memory_mb_none_returns_dash():
    """Missing memory renders as an em-dash placeholder."""
    assert _format_memory_mb(None) == "—"


def _make_game_for_link() -> Game:
    """Create a unique Game row usable by the game-link tests."""
    unique = f"link-{uuid.uuid4().hex[:8]}"
    return Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


@pytest.mark.django_db
def test_game_link_for_resolves_pk_to_slug():
    """A numeric-string current_game_id is looked up and linked by slug."""
    game = _make_game_for_link()
    label, url = _game_link_for(str(game.pk))
    assert label == f"#{game.pk}"
    assert url is not None
    assert game.slug in url


@pytest.mark.django_db
def test_game_link_for_unknown_pk_returns_label_only():
    """An unknown id yields a label but no URL."""
    label, url = _game_link_for("nonexistent-id")
    assert label == "#nonexistent-id"
    assert url is None


def test_game_link_for_empty_returns_dash():
    """Missing/empty input renders as an em-dash placeholder."""
    label, url = _game_link_for("")
    assert label == "—"
    assert url is None
    label2, url2 = _game_link_for(None)
    assert label2 == "—"
    assert url2 is None


def _make_completed_job_for_rate(engine: str, minutes_ago: float) -> AnalysisJob:
    """Create a completed AnalysisJob completed ``minutes_ago`` minutes ago."""
    completed_at = timezone.now() - timedelta(minutes=minutes_ago)
    unique = f"rate-{uuid.uuid4().hex[:8]}"
    game = Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )
    return AnalysisJob.objects.create(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=60.0,
        started_at=completed_at - timedelta(seconds=60),
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_rate_per_min_returns_zero_when_no_recent_completions():
    """No recent completions → 0.0 jobs/min."""
    rate = _rate_per_min("stockfish", window_minutes=10)
    assert rate == 0.0


@pytest.mark.django_db
def test_rate_per_min_counts_completions_inside_window():
    """Five completions in the window → 0.5 jobs/min."""
    for i in range(5):
        _make_completed_job_for_rate("stockfish", minutes_ago=float(i))
    rate = _rate_per_min("stockfish", window_minutes=10)
    assert rate == pytest.approx(0.5)


def test_eta_for_zero_rate_returns_none():
    """Rate of 0 → ETA is ``None`` (renders as ``—``)."""
    assert _eta_for(pending=42, rate_per_min=0.0) is None


def test_eta_for_returns_formatted_string():
    """Pending/rate combinations across seconds/minutes/hours buckets."""
    assert _eta_for(pending=60, rate_per_min=1.0) == "1h 0m"
    assert _eta_for(pending=30, rate_per_min=1.0) == "30m"
    assert _eta_for(pending=5, rate_per_min=10.0) == "30s"


def _make_completed(game, engine, duration_seconds, completed_at):
    """Create a completed AnalysisJob for ``game``/``engine`` at ``completed_at``."""
    return AnalysisJob.objects.create(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=duration_seconds,
        started_at=completed_at - timedelta(seconds=duration_seconds),
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_group_recent_returns_empty_when_no_jobs():
    """Empty DB → empty list."""
    assert _group_recent_by_game(limit=25) == []


@pytest.mark.django_db
def test_group_recent_groups_by_game_and_pivots_engines():
    """One game with both engines complete → single row, both columns filled."""
    game = _make_game_for_link()
    now = timezone.now()
    _make_completed(game, "stockfish", 252.0, now - timedelta(minutes=2))
    _make_completed(game, "lc0", 663.0, now - timedelta(minutes=1))

    rows = _group_recent_by_game(limit=25)

    assert len(rows) == 1
    row = rows[0]
    assert row["game_id"] == str(game.pk)
    assert row["stockfish_seconds"] == 252.0
    assert row["lc0_seconds"] == 663.0
    assert row["latest_completed_at"] is not None


@pytest.mark.django_db
def test_group_recent_handles_partial_completion():
    """A game with only stockfish done → lc0 column is None."""
    game = _make_game_for_link()
    now = timezone.now()
    _make_completed(game, "stockfish", 100.0, now - timedelta(minutes=5))

    rows = _group_recent_by_game(limit=25)

    assert len(rows) == 1
    row = rows[0]
    assert row["stockfish_seconds"] == 100.0
    assert row["lc0_seconds"] is None


@pytest.mark.django_db
def test_group_recent_orders_by_latest_completion_desc():
    """Most recently completed game appears first."""
    older = _make_game_for_link()
    newer = _make_game_for_link()
    now = timezone.now()
    _make_completed(older, "stockfish", 60.0, now - timedelta(hours=1))
    _make_completed(newer, "stockfish", 60.0, now - timedelta(minutes=1))

    rows = _group_recent_by_game(limit=25)

    assert [r["game_id"] for r in rows] == [str(newer.pk), str(older.pk)]


@pytest.mark.django_db
def test_group_recent_respects_limit():
    """``limit`` caps the number of distinct games returned."""
    now = timezone.now()
    for i in range(30):
        g = _make_game_for_link()
        _make_completed(g, "stockfish", 60.0, now - timedelta(minutes=i))

    assert len(_group_recent_by_game(limit=25)) == 25


@pytest.mark.django_db
def test_group_recent_tracks_latest_completed_at_per_game():
    """A second job for the same game must bump ``latest_completed_at``."""
    game = _make_game_for_link()
    now = timezone.now()
    # Earliest job becomes the seed; later job for the same game must
    # update ``latest_completed_at`` (covers line 393).
    _make_completed(game, "stockfish", 60.0, now - timedelta(minutes=5))
    _make_completed(game, "lc0", 90.0, now - timedelta(minutes=1))

    rows = _group_recent_by_game(limit=25)

    matching = [r for r in rows if r["game_id"] == str(game.pk)]
    assert len(matching) == 1
    assert matching[0]["stockfish_seconds"] == 60
    assert matching[0]["lc0_seconds"] == 90


def test_percentile_returns_none_for_empty_input():
    """Percentile of an empty list is None."""
    assert _percentile([], 0.5) is None


def test_percentile_returns_single_value_directly():
    """A one-element list returns that element unchanged."""
    assert _percentile([42.0], 0.95) == 42.0


def test_percentile_interpolates_between_neighbors():
    """Interpolated percentile sits between bracketing values."""
    # p50 of [0, 10, 20, 30, 40] is exactly 20.0
    assert _percentile([0.0, 10.0, 20.0, 30.0, 40.0], 0.5) == 20.0
    # p25 of [0, 10, 20, 30] = 7.5 (interpolated between 0 and 10)
    assert _percentile([0.0, 10.0, 20.0, 30.0], 0.25) == 7.5


@pytest.mark.django_db
def test_throughput_for_window_returns_one_row_per_engine():
    """``_throughput_for_window`` returns one row each for stockfish + lc0."""
    rows = _throughput_for_window(hours=24)
    engines = [r["engine"] for r in rows]
    assert engines == ["stockfish", "lc0"]


@pytest.mark.django_db
def test_engine_throughput_row_with_completed_jobs():
    """A populated window reports non-None p50/p95 + a positive games_per_hour."""
    now = timezone.now()
    for duration in (30.0, 60.0, 90.0, 120.0):
        game = _make_game_for_link()
        _make_completed(game, "stockfish", duration, now - timedelta(minutes=10))

    row = _engine_throughput_row("stockfish", hours=24)

    assert row["completed"] == 4
    assert row["p50_seconds"] is not None
    assert row["p95_seconds"] is not None
    assert row["games_per_hour"] is not None


@pytest.mark.django_db
def test_worker_log_url_for_returns_none_without_prefix():
    """Missing ``claimed_by_key_prefix`` yields no log URL."""
    game = _make_game_for_link()
    job = AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_FAILED,
        error_message="boom",
        completed_at=timezone.now(),
    )
    assert _worker_log_url_for(job) is None


@pytest.mark.django_db
def test_worker_log_url_for_returns_admin_url_when_match_exists():
    """A WorkerLogUpload within ±1h of the failure produces an admin URL."""
    from api.models import WorkerAPIKey, WorkerLogUpload

    api_key, _ = WorkerAPIKey.objects.create_key(
        name="dash-test-worker",
        worker_name="dash-test-worker",
    )
    prefix = api_key.prefix

    game = _make_game_for_link()
    failed_at = timezone.now()
    job = AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_FAILED,
        error_message="boom",
        completed_at=failed_at,
        claimed_by_key_prefix=prefix,
    )
    upload = WorkerLogUpload.objects.create(
        worker=api_key,
        bucket_key="logs/dash-test/1.log",
        size_bytes=42,
        reason=WorkerLogUpload.REASON_CRASH,
    )

    url = _worker_log_url_for(job)

    assert url is not None
    assert str(upload.pk) in url


@pytest.mark.django_db
def test_worker_log_url_for_returns_none_when_no_upload_in_window():
    """A prefix with no upload within ±1h still yields None."""
    from api.models import WorkerAPIKey

    api_key, _ = WorkerAPIKey.objects.create_key(
        name="dash-test-worker-empty",
        worker_name="dash-test-worker-empty",
    )
    game = _make_game_for_link()
    job = AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_FAILED,
        error_message="boom",
        completed_at=timezone.now(),
        claimed_by_key_prefix=api_key.prefix,
    )
    assert _worker_log_url_for(job) is None
