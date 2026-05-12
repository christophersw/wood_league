"""
Title: test_views_queues_summary.py — Tests for the analysis queues summary page
Description: Verifies queues_summary view renders engine cards and is admin-only.
    Covers the renamed status → queues_summary view (Task 5) and the URL rename
    to /admin/queues/ (Task 4 of analysis-queue-ui-overhaul).
    Task 9: adds test for pending_high sub-count in context and template output.
Changelog:
    2026-05-11: Task 9 — add test_summary_shows_pending_high_badge for new
        pending_high context key and HIGH badge rendering.
    2026-05-11: Task 4 — update reverse() calls to use 'analysis:queues_summary'.
    2026-05-11: Initial — Task 5 of analysis-queue-ui-overhaul plan.
"""
import uuid

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


def _make_user(role: str) -> User:
    """Create a User with the given role and a unique email.

    Args:
        role: The user role string, e.g. ``"admin"`` or ``"player"``.

    Returns:
        User: A saved User instance with the requested role.
    """
    return User.objects.create_user(
        email=f"{role}-qs-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only password
        role=role,
    )


def test_summary_renders_engine_cards(db, client):
    """Summary page renders 200 and contains both engine names with detail page links.

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.
    """
    admin = _make_user("admin")
    client.force_login(admin)
    resp = client.get(reverse("analysis:queues_summary"))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "stockfish" in body.lower()
    assert "lc0" in body.lower()
    assert reverse("analysis:queue_stockfish") in body
    assert reverse("analysis:queue_lc0") in body


def test_summary_requires_admin(db, client):
    """Non-admin users are denied (redirect to login or 403).

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.
    """
    player = _make_user("player")
    client.force_login(player)
    resp = client.get(reverse("analysis:queues_summary"))
    assert resp.status_code in (302, 403)


def _make_game(suffix: str = "") -> Game:
    """Create a minimal Game instance required for AnalysisJob FK.

    Args:
        suffix: Optional suffix added to the game ID for uniqueness.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"qs9-{suffix}-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


def test_summary_shows_pending_high_badge(db, client):
    """When HIGH-priority stockfish jobs exist, the HIGH badge appears in the page.

    Creates two pending stockfish jobs — one at HIGH priority, one at NORMAL —
    then checks that the rendered summary page contains the HIGH badge text with
    the correct count. The badge is only rendered when pending_high > 0.

    Args:
        db: pytest-django database fixture.
        client: Django test client fixture.
    """
    # Create one HIGH-priority pending job for stockfish
    AnalysisJob.objects.create(
        game=_make_game("high"),
        engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_HIGH,
    )
    # Create one NORMAL-priority pending job — should not count toward pending_high
    AnalysisJob.objects.create(
        game=_make_game("normal"),
        engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )

    admin = _make_user("admin")
    client.force_login(admin)
    resp = client.get(reverse("analysis:queues_summary"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The HIGH badge should appear because pending_high == 1
    assert "HIGH" in body
    assert "1 HIGH" in body
