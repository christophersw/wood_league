"""
Title: test_enqueue.py — Dedup matrix for enqueue_analysis_job
Description: Six cases: no-existing creates; pending/running/submitted skip;
    completed at sufficient depth skips; completed at lower depth creates.
    Plus the 0-move-PGN guard (#112): refuses to enqueue games that have
    no analysable moves so workers don't loop them through retries.
    Follows the pattern established in test_models_last_error.py (Task A2) —
    objects created directly without pytest-django db fixture.
Changelog:
    2026-05-10: Initial — Task A3 of scrap-dispatchers plan.
    2026-05-11: Add race-path test (Task 3 of enqueue-race-safe plan).
    2026-05-15: Cover 0-move-PGN skip path (issue #112); test fixture
        now uses a real 2-ply PGN so other cases still create jobs.
"""
import uuid
from unittest.mock import patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from analysis.models import AnalysisJob
from analysis.services.enqueue import _pgn_has_moves, enqueue_analysis_job
from games.models import Game

# Minimal real PGN — two plies, enough for python-chess to parse a move so
# the issue #112 guard treats this as analysable.
_REAL_PGN = "1. e4 e5 *"


def _make_game(pgn: str = _REAL_PGN) -> Game:
    """Create a minimal Game instance with a unique ID to avoid collision across runs.

    Args:
        pgn: Override for the game's PGN body. Defaults to a real 2-ply
            opening so the enqueue guard does not short-circuit.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"test-A3-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn=pgn,
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


# ── Issue #112: skip 0-move PGNs at enqueue time ─────────────────────────


@pytest.mark.parametrize("pgn", [
    "",                                            # empty
    "   \n\n",                                     # whitespace only
    '[Event "x"]\n[Result "*"]\n\n*',              # headers only, no moves
    "this is not a pgn",                           # unparseable
])
def test_pgn_has_moves_false_for_empty_inputs(pgn):
    """Issue #112: the guard returns False for any input without playable moves."""
    assert _pgn_has_moves(pgn) is False


@pytest.mark.parametrize("pgn", [
    "1. e4 e5 *",
    "1. d4 *",
    '[Event "x"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 1-0',
])
def test_pgn_has_moves_true_for_real_games(pgn):
    """Issue #112: any PGN with at least one ply must be accepted."""
    assert _pgn_has_moves(pgn) is True


@pytest.mark.django_db
def test_enqueue_skips_when_game_has_no_moves():
    """Issue #112: don't create a job for a game whose PGN parses to 0 plies.

    Workers raise ``ValueError("PGN has no moves …")`` for these and the
    job would loop through retries before reaching MAX_JOB_RETRIES. Refuse
    to enqueue in the first place.
    """
    game = _make_game(pgn="")
    result = enqueue_analysis_job(game=game, engine="stockfish", depth=20)
    assert result is None
    assert AnalysisJob.objects.filter(game=game).count() == 0


@pytest.mark.django_db
def test_enqueue_skips_when_pgn_headers_only():
    """Issue #112: header-only PGNs (forfeits before move 1) are also skipped."""
    game = _make_game(pgn='[Event "x"]\n[Result "0-1"]\n\n0-1')
    result = enqueue_analysis_job(game=game, engine="lc0", depth=25000)
    assert result is None
    assert AnalysisJob.objects.filter(game=game).count() == 0
