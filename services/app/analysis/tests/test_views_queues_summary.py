"""
Title: test_views_queues_summary.py — Tests for the analysis queues summary page
Description: Verifies queues_summary view renders engine cards and is admin-only.
    Covers the renamed status → queues_summary view (Task 5 of analysis-queue-ui-overhaul).
    Until URL rename (Task 4), the route name 'analysis:status' still resolves.
Changelog:
    2026-05-11: Initial — Task 5 of analysis-queue-ui-overhaul plan.
"""
import uuid

from django.urls import reverse

from accounts.models import User


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
    # Until URL rename (Task 4), the route name 'analysis:status' still resolves.
    resp = client.get(reverse("analysis:status"))
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
    resp = client.get(reverse("analysis:status"))
    assert resp.status_code in (302, 403)
