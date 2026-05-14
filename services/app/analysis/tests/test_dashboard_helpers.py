"""
Title: test_dashboard_helpers.py — Unit tests for dashboard helpers
Description:
    Pure-function tests for the dashboard's liveness, uptime, hardware,
    rate, ETA, game-link, and recent-game grouping helpers.

Changelog:
    2026-05-14 (#106): Initial test module.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from analysis.dashboard_helpers import (
    LIVENESS_HEALTHY_SECONDS,
    LIVENESS_WARNING_SECONDS,
    _eta_for,
    _format_memory_mb,
    _format_uptime,
    _game_link_for,
    _liveness_for,
    _rate_per_min,
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
