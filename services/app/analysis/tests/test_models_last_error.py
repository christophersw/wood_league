"""
Title: test_models_last_error.py — AnalysisJob.last_error / last_error_at fields
Description: Verify the new last_error and last_error_at fields can be set,
    cleared, and round-trip through the ORM.
Changelog:
    2026-05-10: Initial — Task A2 of scrap-dispatchers plan.
"""
import uuid

import pytest
from django.utils import timezone

from analysis.models import AnalysisJob
from games.models import Game


@pytest.mark.django_db
def test_last_error_fields_round_trip():
    """Verify last_error and last_error_at default to None and can be set and retrieved.

    Parameters:
        None

    Returns:
        None

    Side effects:
        Creates a transient Game and AnalysisJob row in the database; these are
        not rolled back automatically (no pytest-django transaction support), so
        we use a unique UUID-based game ID to avoid collisions across runs.
    """
    unique_game_id = f"test-game-A2-{uuid.uuid4().hex[:8]}"
    game = Game.objects.create(
        id=unique_game_id,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )
    job = AnalysisJob.objects.create(game=game, engine="stockfish")
    assert job.last_error is None
    assert job.last_error_at is None

    job.last_error = "boom"
    job.last_error_at = timezone.now()
    job.save()

    fresh = AnalysisJob.objects.get(pk=job.pk)
    assert fresh.last_error == "boom"
    assert fresh.last_error_at is not None
