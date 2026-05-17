"""
Title: test_dashboard_view.py — Tests for /admin/dashboard/
Description:
    Verifies the dashboard shell and its six HTMX partials each return
    200 to admin users, the page contains all six partial wrappers, the
    legacy /admin/diagnostics/ URL redirects to /admin/dashboard/, and
    non-admin users cannot access any of these endpoints.

Changelog:
    2026-05-14 (#106): Initial smoke tests for the wire-up slice.
    2026-05-14 (#106): Regression test for naive last_seen TypeError.
    2026-05-17 (#128): Test stale-drop, live/reporting flags, and card shape.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob, WorkerHeartbeat


def _make_user(role: str) -> User:
    """Create a test user with the given role."""
    return User.objects.create_user(
        email=f"{role}-dash-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only
        role=role,
    )


@pytest.mark.django_db
def test_dashboard_shell_renders_for_admin(client):
    """The shell page returns 200 and contains all six partial wrappers."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    for wrapper_id in (
        "dash-banner", "dash-workers", "dash-queues",
        "dash-throughput", "dash-recent", "dash-failures",
    ):
        assert f'id="{wrapper_id}"' in content


@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "dash_banner", "dash_workers", "dash_queues",
    "dash_throughput", "dash_recent", "dash_failures",
])
def test_each_partial_renders_for_admin(client, name):
    """Each of the six partial endpoints returns 200 for an admin."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse(f"analysis:{name}"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_diagnostics_redirects_to_dashboard(client):
    """Legacy /admin/diagnostics/ URL 302s to /admin/dashboard/."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:diagnostics"))

    assert response.status_code == 302
    assert response.url.endswith(reverse("analysis:dashboard"))


@pytest.mark.django_db
def test_dashboard_requires_admin(client):
    """Non-admin users get a redirect (login) on the dashboard URL."""
    player = _make_user("player")
    client.force_login(player)

    response = client.get(reverse("analysis:dashboard"))

    # staff_member_required redirects to admin login
    assert response.status_code == 302


def _make_dash_game(suffix: str = ""):
    """Create a minimal Game row usable for URL reversal in dashboard tests."""
    from games.models import Game

    unique = f"dash-{suffix}-{uuid.uuid4().hex[:8]}"
    return Game.objects.create(
        id=unique,
        slug=unique,
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


def _make_completed_job(engine: str, duration: float = 60.0,
                        minutes_ago: float = 1.0) -> AnalysisJob:
    """Create a completed AnalysisJob with the given duration."""
    completed_at = timezone.now() - timedelta(minutes=minutes_ago)
    return AnalysisJob.objects.create(
        game=_make_dash_game(engine),
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=duration,
        started_at=completed_at - timedelta(seconds=duration),
        completed_at=completed_at,
    )


@pytest.mark.django_db
def test_banner_reports_worker_and_job_counts(client):
    """Banner shows ``healthy/total`` workers, pending count, and done-today."""
    admin = _make_user("admin")
    client.force_login(admin)

    now = timezone.now()
    WorkerHeartbeat.objects.create(
        worker_id="w-fresh", status="working", engine="stockfish",
    )
    stale = WorkerHeartbeat.objects.create(
        worker_id="w-stale", status="working", engine="lc0",
    )
    WorkerHeartbeat.objects.filter(pk=stale.pk).update(
        last_seen=now - timedelta(minutes=10),
    )

    _make_completed_job("stockfish", duration=60.0, minutes_ago=30)

    response = client.get(reverse("analysis:dash_banner"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "1/2" in body  # 1 healthy / 2 total


@pytest.mark.django_db
def test_workers_partial_lists_each_heartbeat(client):
    """Each live WorkerHeartbeat produces a card with its worker_id and engine."""
    admin = _make_user("admin")
    client.force_login(admin)

    # last_seen auto_now → just-created → within the "live" window; no stale drop.
    WorkerHeartbeat.objects.create(
        worker_id="runpod-stockfish",
        engine="stockfish",
        status="working",
        jobs_completed=6,
        jobs_failed=0,
        cpu_model="EPYC 75F3",
        cpu_cores=16,
        memory_mb=62000,
    )

    response = client.get(reverse("analysis:dash_workers"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "runpod-stockfish" in body
    assert "stockfish" in body.lower()
    # New card shape: verify live_state is present in rendered template
    cards = response.context["cards"]
    assert any(c["worker_id"] == "runpod-stockfish" for c in cards)
    card = next(c for c in cards if c["worker_id"] == "runpod-stockfish")
    assert card["live_state"] == "live"


@pytest.mark.django_db
def test_queues_partial_lists_both_engines(client):
    """Queues partial renders one row per engine with counts + rate."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:dash_queues"))

    assert response.status_code == 200
    body = response.content.decode()
    assert "stockfish" in body.lower()
    assert "lc0" in body.lower()


@pytest.mark.django_db
def test_recent_partial_links_to_game_page(client):
    """Each row links to the per-game analysis page using the slug."""
    admin = _make_user("admin")
    client.force_login(admin)

    game = _make_dash_game("recent")
    now = timezone.now()
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_COMPLETED,
        duration_seconds=252.0,
        started_at=now - timedelta(minutes=5),
        completed_at=now - timedelta(minutes=2),
    )

    response = client.get(reverse("analysis:dash_recent"))

    assert response.status_code == 200
    body = response.content.decode()
    assert game.slug in body
    assert "252s" in body


@pytest.mark.django_db
def test_failures_partial_lists_recent_failures(client):
    """A failed AnalysisJob shows up in the failures partial."""
    admin = _make_user("admin")
    client.force_login(admin)

    game = _make_dash_game("fail")
    AnalysisJob.objects.create(
        game=game, engine="stockfish",
        status=AnalysisJob.STATUS_FAILED,
        error_message="boom",
        completed_at=timezone.now(),
    )

    response = client.get(reverse("analysis:dash_failures"))

    assert response.status_code == 200
    assert "boom" in response.content.decode()


@pytest.mark.django_db
def test_banner_handles_naive_last_seen(client):
    """Banner must not raise TypeError when ``last_seen`` is TZ-naive.

    Legacy DB rows that pre-date ``USE_TZ=True`` may carry naive datetimes.
    Subtracting a naive datetime from a TZ-aware ``timezone.now()`` raises
    TypeError; the view coerces naive values defensively.
    """
    admin = _make_user("admin")
    client.force_login(admin)

    heartbeat = WorkerHeartbeat.objects.create(
        worker_id="w-legacy-naive", status="working", engine="stockfish",
    )
    naive_dt = datetime(2026, 5, 14, 12, 0, 0)  # noqa: DTZ001 — intentionally naive
    assert naive_dt.tzinfo is None
    WorkerHeartbeat.objects.filter(pk=heartbeat.pk).update(last_seen=naive_dt)

    response = client.get(reverse("analysis:dash_banner"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_throughput_partial_lists_engines_and_windows(client):
    """Throughput partial renders one row per engine and 1h/6h/24h columns."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:dash_throughput"))

    assert response.status_code == 200
    body = response.content.decode()
    for header in ("Stockfish", "Lc0", "1h", "6h", "24h"):
        assert header in body


def _setup_workers_card_fixtures(now):
    """Create three WorkerHeartbeat rows (live, reporting, dead) and one completed job.

    Args:
        now: TZ-aware datetime representing the test's "current" moment.

    Returns:
        None — creates rows in the DB as a side effect.
    """
    from analysis.models import AnalysisJob, WorkerHeartbeat
    from games.models import Game

    live = WorkerHeartbeat.objects.create(
        worker_id="live-1", engine="lc0", batch_total=6, batch_processed=2,
        session_started_at=now - timedelta(seconds=600),
    )
    WorkerHeartbeat.objects.filter(pk=live.pk).update(last_seen=now - timedelta(seconds=30))

    reporting = WorkerHeartbeat.objects.create(worker_id="rep-1", engine="lc0")
    WorkerHeartbeat.objects.filter(pk=reporting.pk).update(
        last_seen=now - timedelta(seconds=600)
    )

    dead = WorkerHeartbeat.objects.create(worker_id="dead-1", engine="lc0")
    WorkerHeartbeat.objects.filter(pk=dead.pk).update(
        last_seen=now - timedelta(seconds=4000)
    )

    g = Game.objects.create(
        id="dv-1", slug="dv-1", played_at=now, time_control="600", pgn="*",
    )
    AnalysisJob.objects.create(
        game=g, engine="lc0", status=AnalysisJob.STATUS_COMPLETED,
        worker_id="live-1", duration_seconds=12.0, completed_at=now,
    )


def _assert_live_card_shape(card):
    """Assert the card dict for worker live-1 has the expected shape and values.

    Args:
        card: Card dict from ``resp.context["cards"]`` for worker_id ``"live-1"``.

    Returns:
        None — raises AssertionError if any field is unexpected.
    """
    assert card["batch_total"] == 6 and card["batch_processed"] == 2
    assert card["batch_percent"] == pytest.approx(33.33, abs=0.1)
    assert any(r["engine"] == "lc0" for r in card["engine_rows"])
    assert card["billable_per_game"] is not None
    assert isinstance(card["recent_games"], list)


@pytest.mark.django_db
def test_dashboard_workers_drops_stale_flags_live_and_builds_cards(client):
    """Workers partial drops stale workers, flags live/reporting, and emits rich cards."""
    client.force_login(_make_user("admin"))
    now = timezone.now()
    _setup_workers_card_fixtures(now)

    resp = client.get(reverse("analysis:dash_workers"))
    assert resp.status_code == 200
    ids = {c["worker_id"]: c for c in resp.context["cards"]}

    assert "dead-1" not in ids
    assert ids["live-1"]["live_state"] == "live"
    assert ids["rep-1"]["live_state"] == "reporting"
    _assert_live_card_shape(ids["live-1"])
