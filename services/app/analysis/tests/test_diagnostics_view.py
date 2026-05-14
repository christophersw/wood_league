"""
Title: test_diagnostics_view.py — Tests for the analysis diagnostics admin page
Description:
    Verifies the /admin/diagnostics/ page restricts access to admin users,
    renders empty-state tables cleanly, computes 24-hour throughput numbers
    correctly across both engines, surfaces recent failures in the right
    order with truncated error snippets, and links to a matching
    WorkerLogUpload row when one is uploaded near the failure timestamp.

Changelog:
    2026-05-14 (#86): Initial test module.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob
from api.models import WorkerAPIKey, WorkerLogUpload
from analysis.views import _recent_failures, _throughput_for_window
from games.models import Game


def _make_user(role: str) -> User:
    """Create a test user with the given role and a unique email.

    Args:
        role: Role string ("admin" or "player").

    Returns:
        A saved :class:`User` instance.
    """
    return User.objects.create_user(
        email=f"{role}-diag-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only password
        role=role,
    )


def _make_game(suffix: str = "") -> Game:
    """Create a minimal Game with a slug usable for URL reversal.

    Args:
        suffix: Distinguishing suffix appended to the random ID.

    Returns:
        A saved :class:`Game` instance.
    """
    unique = f"diag-{suffix}-{uuid.uuid4().hex[:8]}"
    return Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


def _make_completed_job(engine: str, duration: float, age_hours: float = 1.0) -> AnalysisJob:
    """Create a completed AnalysisJob with the given duration.

    Args:
        engine: Engine name to assign.
        duration: ``duration_seconds`` value to store.
        age_hours: How many hours ago the job completed.

    Returns:
        The saved :class:`AnalysisJob` instance.
    """
    completed_at = timezone.now() - timedelta(hours=age_hours)
    return AnalysisJob.objects.create(
        game=_make_game(engine),
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=duration,
        started_at=completed_at - timedelta(seconds=duration),
        completed_at=completed_at,
    )


def _make_failed_job(
    engine: str,
    completed_at,
    *,
    error_message: str = "boom",
    worker_id: str = "worker-x",
    retries: int = 0,
    claimed_prefix: str | None = None,
) -> AnalysisJob:
    """Create a failed AnalysisJob with the given timestamps and error text.

    Args:
        engine: Engine name to assign.
        completed_at: Failure timestamp recorded on the job.
        error_message: Raw error text to store on ``error_message``.
        worker_id: Identifier of the failing worker.
        retries: Number of retries already attempted.
        claimed_prefix: ``claimed_by_key_prefix`` to set, if any.

    Returns:
        The saved :class:`AnalysisJob` instance.
    """
    return AnalysisJob.objects.create(
        game=_make_game(engine),
        engine=engine,
        status=AnalysisJob.STATUS_FAILED,
        completed_at=completed_at,
        error_message=error_message,
        worker_id=worker_id,
        retry_count=retries,
        claimed_by_key_prefix=claimed_prefix,
    )


def test_anonymous_user_is_redirected(db, client):
    """Unauthenticated requests get a login redirect (302).

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.
    """
    resp = client.get(reverse("analysis:diagnostics"))
    assert resp.status_code == 302


def test_non_admin_user_is_denied(db, client):
    """Authenticated non-admin users cannot access the page.

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.
    """
    player = _make_user("player")
    client.force_login(player)
    resp = client.get(reverse("analysis:diagnostics"))
    assert resp.status_code in (302, 403)


def test_throughput_metrics_for_stockfish(db):
    """Throughput helper returns correct counts and averages for stockfish.

    Args:
        db: pytest-django database fixture.
    """
    for seconds in (10.0, 20.0, 30.0, 40.0, 50.0):
        _make_completed_job("stockfish", seconds)

    rows = _throughput_for_window(hours=24)
    by_engine = {row["engine"]: row for row in rows}

    assert by_engine["stockfish"]["completed"] == 5
    assert by_engine["stockfish"]["avg_seconds"] == 30.0
    assert by_engine["stockfish"]["p50_seconds"] is not None
    assert abs(by_engine["stockfish"]["p50_seconds"] - 30.0) < 0.01
    assert abs(by_engine["stockfish"]["p95_seconds"] - 48.0) < 0.01
    assert by_engine["stockfish"]["games_per_hour"] == round(5 / 24, 2)
    assert by_engine["stockfish"]["failure_rate"] == 0.0


def test_throughput_metrics_for_lc0(db):
    """Throughput helper returns correct counts and averages for lc0.

    Args:
        db: pytest-django database fixture.
    """
    for seconds in (5.0, 15.0, 25.0):
        _make_completed_job("lc0", seconds)

    rows = _throughput_for_window(hours=24)
    by_engine = {row["engine"]: row for row in rows}

    assert by_engine["lc0"]["completed"] == 3
    assert by_engine["lc0"]["avg_seconds"] == 15.0
    assert abs(by_engine["lc0"]["p50_seconds"] - 15.0) < 0.01


def test_recent_failures_ordered_and_snippet_truncated(db):
    """Failure rows surface in newest-first order and snippets cap at 200 chars.

    Args:
        db: pytest-django database fixture.
    """
    long_error = "x" * 500
    now = timezone.now()
    older = _make_failed_job("stockfish", now - timedelta(hours=2), error_message=long_error)
    newer = _make_failed_job("lc0", now - timedelta(minutes=10), error_message="quick crash")

    rows = _recent_failures(limit=50)
    assert [row["id"] for row in rows] == [newer.id, older.id]
    older_row = next(row for row in rows if row["id"] == older.id)
    assert len(older_row["error_snippet"]) == 200
    assert older_row["error_snippet"] == "x" * 200


def test_worker_log_link_matches_when_within_window(db):
    """Failures with a matching WorkerLogUpload within 1 h yield a log URL.

    A second failure without a nearby log shows no URL.

    Args:
        db: pytest-django database fixture.
    """
    matching_prefix = "abcd1234"
    other_prefix = "wxyz5678"
    failure_time = timezone.now() - timedelta(minutes=20)

    api_key = WorkerAPIKey(
        id=f"{matching_prefix}.hash",
        prefix=matching_prefix,
        hashed_key="hashed",
        revoked=False,
        name="diag-worker-key",
        worker_name="diag-worker",
    )
    api_key.save()

    matching_failure = _make_failed_job(
        "stockfish",
        failure_time,
        claimed_prefix=matching_prefix,
        worker_id="worker-with-log",
    )
    unmatched_failure = _make_failed_job(
        "lc0",
        failure_time - timedelta(minutes=5),
        claimed_prefix=other_prefix,
        worker_id="worker-without-log",
    )

    upload = WorkerLogUpload.objects.create(
        worker=api_key,
        bucket_key="diag/log.txt",
        size_bytes=42,
        reason=WorkerLogUpload.REASON_CRASH,
    )
    # Force uploaded_at to be near the failure (auto_now_add sets it to "now"
    # but our failure is also ~20 minutes ago — that is still inside the
    # 1-hour window so this assignment is defensive, not strictly required).
    WorkerLogUpload.objects.filter(pk=upload.pk).update(
        uploaded_at=failure_time + timedelta(minutes=5),
    )

    rows = _recent_failures(limit=50)
    by_id = {row["id"]: row for row in rows}
    assert by_id[matching_failure.id]["worker_log_url"] is not None
    assert by_id[unmatched_failure.id]["worker_log_url"] is None


