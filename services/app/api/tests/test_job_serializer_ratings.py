"""
Title: test_job_serializer_ratings.py — Tests for JobSerializer rating fields
Description:
    Verifies that JobSerializer exposes white_rating and black_rating from
    the related game object, enabling workers to receive player Elo ratings
    for WDL calibration (issue #159).

Changelog:
    2026-05-19 (#159): Initial — TDD failing test for rating field exposure
"""
from api.serializers import JobSerializer


class _Game:
    id = "g1"
    pgn = "1. e4 e5"
    white_rating = 900
    black_rating = 1300


class _Job:
    id = 1
    game = _Game()
    engine = "lc0"
    depth = 20
    nodes = 25000
    worker_id = "w"
    claimed_by_key_prefix = "k"


def test_job_serializer_includes_ratings():
    """JobSerializer must expose white_rating and black_rating to workers.

    When a Job has explicit player ratings, the serializer must pass them
    through so the lc0 worker can compute calibration contempt (issue #159).
    """
    data = JobSerializer(_Job()).data
    assert data["white_rating"] == 900 and data["black_rating"] == 1300
