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
    _format_memory_mb,
    _format_uptime,
    _game_link_for,
    _liveness_for,
)
from games.models import Game


def test_liveness_healthy_under_threshold():
    """Deltas below 60s return ``'healthy'``."""
    assert _liveness_for(timedelta(seconds=0)) == "healthy"
    assert _liveness_for(timedelta(seconds=59)) == "healthy"


def test_liveness_warning_between_thresholds():
    """Deltas in [60s, 120s) return ``'warning'``."""
    assert _liveness_for(timedelta(seconds=60)) == "warning"
    assert _liveness_for(timedelta(seconds=119)) == "warning"


def test_liveness_stale_at_or_above_warning_ceiling():
    """Deltas >=120s return ``'stale'``."""
    assert _liveness_for(timedelta(seconds=120)) == "stale"
    assert _liveness_for(timedelta(hours=1)) == "stale"


def test_liveness_none_treated_as_stale():
    """A missing delta (no heartbeat ever) is ``'stale'``."""
    assert _liveness_for(None) == "stale"


def test_liveness_thresholds_are_constants():
    """Thresholds are exported as module-level constants for reuse."""
    assert LIVENESS_HEALTHY_SECONDS == 60
    assert LIVENESS_WARNING_SECONDS == 120


def test_format_uptime_seconds():
    """Sub-minute uptimes are formatted in seconds."""
    assert _format_uptime(timedelta(seconds=5)) == "5s"
    assert _format_uptime(timedelta(seconds=59)) == "59s"


def test_format_uptime_minutes():
    """Sub-hour uptimes are formatted in minutes."""
    assert _format_uptime(timedelta(minutes=1)) == "1m"
    assert _format_uptime(timedelta(minutes=22, seconds=30)) == "22m"
    assert _format_uptime(timedelta(minutes=59, seconds=59)) == "59m"


def test_format_uptime_hours_and_days():
    """Long uptimes show hours, then days+hours."""
    assert _format_uptime(timedelta(hours=1)) == "1h 0m"
    assert _format_uptime(timedelta(hours=3, minutes=12)) == "3h 12m"
    assert _format_uptime(timedelta(days=1, hours=4)) == "1d 4h"
    assert _format_uptime(timedelta(days=10)) == "10d 0h"


def test_format_uptime_none_returns_dash():
    """Missing started_at renders as an em-dash placeholder."""
    assert _format_uptime(None) == "—"


def test_format_memory_mb_rounds_to_gb_above_1024():
    """Memory >=1024 MB renders as GB to one decimal."""
    assert _format_memory_mb(62000) == "60.5 GB"
    assert _format_memory_mb(1024) == "1.0 GB"


def test_format_memory_mb_keeps_megabytes_below_1024():
    """Memory <1024 MB stays in MB."""
    assert _format_memory_mb(512) == "512 MB"


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
