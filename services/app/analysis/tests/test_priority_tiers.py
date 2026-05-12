"""
Title: test_priority_tiers.py — Tests for AnalysisJob priority tier constants and ordering
Description: Verifies HIGH/NORMAL/LOW priority constants and that pending jobs
    sort by priority desc then game.played_at desc for both admin display and
    worker claim.
Changelog:
    2026-05-11: Initial — Task 1 of analysis-queue-ui-overhaul plan.
    2026-05-11: Task 2 — Add worker claim ordering tests by played_at.
"""
import pytest
from datetime import datetime, timezone as dt_tz
from django.contrib.auth import get_user_model

from analysis.models import AnalysisJob
from analysis.services.jobs import claim_jobs
from games.models import Game


def test_priority_tier_constants_exist():
    """Three named priority tiers expose integer values, HIGH > NORMAL > LOW."""
    assert AnalysisJob.PRIORITY_HIGH > AnalysisJob.PRIORITY_NORMAL > AnalysisJob.PRIORITY_LOW
    assert AnalysisJob.PRIORITY_HIGH == 100
    assert AnalysisJob.PRIORITY_NORMAL == 0
    assert AnalysisJob.PRIORITY_LOW == -100


@pytest.fixture
def two_pending_jobs(db):
    """Two pending stockfish jobs at same priority; older played_at vs newer."""
    User = get_user_model()
    User.objects.create_user(email="claim-test@example.com", password="x", role="admin")
    older_game = Game.objects.create(
        id="older_game_1",
        white_username="a", black_username="b",
        played_at=datetime(2024, 1, 1, tzinfo=dt_tz.utc),
        time_control="",
    )
    newer_game = Game.objects.create(
        id="newer_game_1",
        white_username="c", black_username="d",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
        time_control="",
    )
    older_job = AnalysisJob.objects.create(
        game=older_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, priority=AnalysisJob.PRIORITY_NORMAL,
    )
    newer_job = AnalysisJob.objects.create(
        game=newer_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, priority=AnalysisJob.PRIORITY_NORMAL,
    )
    return older_job, newer_job


def test_worker_claim_prefers_recent_played_at(two_pending_jobs):
    """Same priority: worker should claim the job whose game was played most recently."""
    older_job, newer_job = two_pending_jobs
    claimed = claim_jobs(
        engine="stockfish", worker_id="w1", key_prefix="abcd1234", batch_size=1,
    )
    assert len(claimed) == 1
    assert claimed[0].id == newer_job.id


def test_worker_claim_high_priority_beats_recent(two_pending_jobs):
    """HIGH priority on the older game still wins over NORMAL on the newer game."""
    older_job, newer_job = two_pending_jobs
    older_job.priority = AnalysisJob.PRIORITY_HIGH
    older_job.save(update_fields=["priority"])
    claimed = claim_jobs(
        engine="stockfish", worker_id="w2", key_prefix="abcd1234", batch_size=1,
    )
    assert len(claimed) == 1
    assert claimed[0].id == older_job.id
