"""
Title: test_views_queue_reorder.py — Tests for POST queue_reorder
Description: Verifies HIGH/LOW bulk priority updates, scoping, validation, admin gating.
Changelog:
    2026-05-11: Initial — Task 6 of analysis-queue-ui-overhaul plan.
"""
import pytest
from datetime import datetime, timezone as dt_tz
from django.contrib.auth import get_user_model
from django.urls import reverse

from analysis.models import AnalysisJob
from games.models import Game


@pytest.fixture
def admin_client(db, client):
    """Create an admin user and return an authenticated client.

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.

    Returns:
        Client: Django test client logged in as an admin user.
    """
    User = get_user_model()
    user = User.objects.create_user(
        email="reorder-admin@example.com", password="x", role="admin",
    )
    client.force_login(user)
    return client


@pytest.fixture
def pending_job(db):
    """Create a pending stockfish AnalysisJob at PRIORITY_NORMAL.

    Args:
        db: pytest-django database fixture.

    Returns:
        AnalysisJob: A pending job for the stockfish engine.
    """
    game = Game.objects.create(
        id="reorder_game_1",
        white_username="w", black_username="b",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
        time_control="",
    )
    return AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )


def test_reorder_top_sets_high(admin_client, pending_job):
    """action='top' should set priority to PRIORITY_HIGH."""
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_HIGH


def test_reorder_bottom_sets_low(admin_client, pending_job):
    """action='bottom' should set priority to PRIORITY_LOW."""
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "bottom"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_LOW


def test_reorder_ignores_wrong_engine(admin_client, pending_job):
    """Jobs for a different engine than the URL should not be updated."""
    url = reverse("analysis:queue_reorder", kwargs={"engine": "lc0"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 200
    pending_job.refresh_from_db()
    assert pending_job.priority == AnalysisJob.PRIORITY_NORMAL


def test_reorder_ignores_non_pending(admin_client, db):
    """Non-pending jobs should not have their priority changed."""
    game = Game.objects.create(
        id="reorder_game_2",
        white_username="w", black_username="b",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
        time_control="",
    )
    job = AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [job.id], "action": "top"})
    assert resp.status_code == 200
    job.refresh_from_db()
    assert job.priority == AnalysisJob.PRIORITY_NORMAL


def test_reorder_bad_action_returns_400(admin_client, pending_job):
    """An unrecognised action value should return HTTP 400."""
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "sideways"})
    assert resp.status_code == 400


def test_reorder_bad_engine_returns_400(admin_client, pending_job):
    """An unrecognised engine in the URL should return HTTP 400."""
    url = reverse("analysis:queue_reorder", kwargs={"engine": "nope"})
    resp = admin_client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code == 400


def test_reorder_requires_admin(db, client, pending_job):
    """A non-admin user should be denied access (302 or 403)."""
    User = get_user_model()
    user = User.objects.create_user(
        email="reorder-player@example.com", password="x", role="player",
    )
    client.force_login(user)
    url = reverse("analysis:queue_reorder", kwargs={"engine": "stockfish"})
    resp = client.post(url, {"job_ids": [pending_job.id], "action": "top"})
    assert resp.status_code in (302, 403)
