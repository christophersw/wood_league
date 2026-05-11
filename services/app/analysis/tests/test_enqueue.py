"""
Title: test_enqueue.py — Dedup matrix for enqueue_analysis_job
Description: Six cases: no-existing creates; pending/running/submitted skip;
    completed at sufficient depth skips; completed at lower depth creates.
    Follows the pattern established in test_models_last_error.py (Task A2) —
    objects created directly without pytest-django db fixture.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
    2026-05-11: Add race-path test (Task 3 of enqueue-race-safe plan).
"""
import uuid
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from analysis.models import AnalysisJob
from analysis.services.enqueue import enqueue_analysis_job
from games.models import Game


def _make_game() -> Game:
    """Create a minimal Game instance with a unique ID to avoid collision across runs.

    Args:
        None

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"test-A3-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


@pytest.mark.django_db
def test_no_existing_creates():
    """Case 1: No existing job for game+engine — should create a new pending job."""
    game = _make_game()
    job = enqueue_analysis_job(game=game, engine="stockfish", depth=20)
    assert job is not None
    assert job.status == AnalysisJob.STATUS_PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("status", [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
])
def test_active_existing_skips(status):
    """Cases 2-4: Active (pending/running/submitted) job exists — should skip creation.

    Args:
        status: One of pending, running, or submitted — injected by parametrize.
    """
    game = _make_game()
    AnalysisJob.objects.create(game=game, engine="stockfish", status=status, depth=20)
    assert enqueue_analysis_job(game=game, engine="stockfish", depth=20) is None


@pytest.mark.django_db
def test_completed_sufficient_depth_skips():
    """Case 5: Completed job at depth >= requested — should skip creation."""
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED, depth=25
    )
    assert enqueue_analysis_job(game=game, engine="stockfish", depth=20) is None


@pytest.mark.django_db
def test_completed_lower_depth_creates():
    """Case 6: Completed job at depth < requested — should create a new job."""
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish", status=AnalysisJob.STATUS_COMPLETED, depth=15
    )
    job = enqueue_analysis_job(game=game, engine="stockfish", depth=20)
    assert job is not None
    assert job.status == AnalysisJob.STATUS_PENDING


@pytest.mark.django_db
@pytest.mark.parametrize("second_status", [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_RUNNING,
    AnalysisJob.STATUS_SUBMITTED,
])
def test_partial_unique_blocks_second_active(second_status):
    """DB-level: a second active job for the same (game, engine) must be rejected.

    Args:
        second_status: Active status for the second insert — parametrized over
            pending/running/submitted.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, depth=20,
    )
    with pytest.raises(IntegrityError):
        AnalysisJob.objects.create(
            game=game, engine="stockfish",
            status=second_status, depth=20,
        )


@pytest.mark.django_db
def test_partial_unique_allows_completed_plus_active():
    """DB-level: completed + active for the same (game, engine) is allowed.

    Only active statuses fall under the partial unique index, so a completed
    job must not block a new pending job.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=20,
    )
    # Should not raise.
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING, depth=25,
    )


@pytest.mark.django_db
def test_partial_unique_allows_two_completed():
    """DB-level: two completed jobs for the same (game, engine) are allowed.

    Completed jobs are outside the partial unique index, so re-analysis
    history can accumulate.
    """
    game = _make_game()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=20,
    )
    # Should not raise.
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED, depth=25,
    )


@pytest.mark.django_db
def test_enqueue_returns_none_when_race_violates_constraint():
    """If a concurrent caller inserts an active row between our .exists()
    pre-check and our .create(), the DB unique constraint rejects the insert.
    The service must swallow the IntegrityError and return None, matching the
    dedup-skip contract.

    Simulated by patching AnalysisJob.objects.create to raise IntegrityError,
    which is exactly what the DB does when a concurrent caller wins the race.
    Patching .create() (rather than the .filter() pre-check) keeps the dedup
    pre-checks real and isolates the race-window path.
    """
    game = _make_game()

    with patch(
        "analysis.services.enqueue.AnalysisJob.objects.create",
        side_effect=IntegrityError("simulated race: unique constraint violation"),
    ):
        result = enqueue_analysis_job(game=game, engine="stockfish", depth=20)

    assert result is None
    # We did not create any rows (the mocked .create() raised before insert).
    assert AnalysisJob.objects.filter(game=game, engine="stockfish").count() == 0
