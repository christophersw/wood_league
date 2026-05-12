"""
Title: test_views_queue.py — Queue detail page tests
Description: Verifies /queue/<engine>/ renders pending AnalysisJobs for the
    engine, requires admin auth, and excludes other engines' jobs. Also
    verifies pending jobs are ordered by priority desc + played_at desc and
    that pagination query params (page, per_page) produce correct Page objects.
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
    2026-05-11: Task 7 — pagination + ordering tests added.
"""
import uuid

import pytest
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


def _make_game(suffix: str = "") -> Game:
    """Create a minimal Game instance with a unique ID.

    Args:
        suffix: Optional suffix to include in the game ID for test clarity.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"qb1-{suffix}-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="*",
    )


def _make_admin() -> User:
    """Create a User with admin role.

    Returns:
        User: A saved admin User instance.
    """
    return User.objects.create_user(
        email=f"admin-{uuid.uuid4().hex[:6]}@test", password="x", role="admin"
    )


def _make_member() -> User:
    """Create a User with member role.

    Returns:
        User: A saved member User instance.
    """
    return User.objects.create_user(
        email=f"member-{uuid.uuid4().hex[:6]}@test", password="x", role="member"
    )


class QueueViewAuthTests(TestCase):
    """Tests for access control on the queue detail pages."""

    def test_requires_admin(self):
        """Non-admin users should be redirected or denied from the queue page."""
        user = _make_member()
        self.client.force_login(user)
        resp = self.client.get(reverse("analysis:queue_stockfish"))
        self.assertIn(resp.status_code, (302, 403))


class StockfishQueueViewTests(TestCase):
    """Tests for the Stockfish queue detail page."""

    def test_lists_pending_for_engine_only(self):
        """Stockfish queue page should show stockfish jobs but not lc0 jobs."""
        admin = _make_admin()
        g1 = _make_game("sf")
        g2 = _make_game("lc")
        AnalysisJob.objects.create(game=g1, engine="stockfish",
                                    status=AnalysisJob.STATUS_PENDING, depth=20)
        AnalysisJob.objects.create(game=g2, engine="lc0",
                                    status=AnalysisJob.STATUS_PENDING, depth=25000)
        self.client.force_login(admin)
        resp = self.client.get(reverse("analysis:queue_stockfish"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(g1.id, body)
        self.assertNotIn(g2.id, body)


class Lc0QueueViewTests(TestCase):
    """Tests for the lc0 queue detail page."""

    def test_lc0_queue_view(self):
        """lc0 queue page should show lc0 pending jobs."""
        admin = _make_admin()
        g = _make_game("only-lc")
        AnalysisJob.objects.create(game=g, engine="lc0",
                                    status=AnalysisJob.STATUS_PENDING, depth=25000)
        self.client.force_login(admin)
        resp = self.client.get(reverse("analysis:queue_lc0"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(g.id, resp.content.decode())


# ---------------------------------------------------------------------------
# pytest-style tests for Task 7: pending ordering + pagination
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(db, client):
    """Return a Django test client logged in as an admin user.

    Args:
        db: pytest-django database fixture.
        client: pytest-django Django test client fixture.

    Returns:
        Client: Django test client with an authenticated admin session.
    """
    User = __import__("accounts.models", fromlist=["User"]).User
    user = User.objects.create_user(
        email="task7-admin@example.com", password="x", role="admin"
    )
    client.force_login(user)
    return client


def test_pending_ordered_by_priority_then_played_at(admin_client, db):
    """Pending table orders by priority desc, then game.played_at desc.

    Args:
        admin_client: Authenticated admin Django test client.
        db: pytest-django database fixture.
    """
    from datetime import datetime, timezone as dt_tz

    old_game = Game.objects.create(
        id="task7_old_game",
        white_username="a", black_username="b",
        played_at=datetime(2024, 1, 1, tzinfo=dt_tz.utc),
        time_control="",
    )
    new_game = Game.objects.create(
        id="task7_new_game",
        white_username="c", black_username="d",
        played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
        time_control="",
    )
    high_old = AnalysisJob.objects.create(
        game=old_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_HIGH,
    )
    normal_new = AnalysisJob.objects.create(
        game=new_game, engine="stockfish",
        status=AnalysisJob.STATUS_PENDING,
        priority=AnalysisJob.PRIORITY_NORMAL,
    )

    resp = admin_client.get(reverse("analysis:queue_stockfish"))
    body = resp.content.decode()
    # Check by game ID (rendered in table cell) which is unique in the page
    assert old_game.id in body
    assert new_game.id in body
    # high priority job (old game) should appear before normal priority job (new game)
    assert body.index(old_game.id) < body.index(new_game.id)
    # Also verify job IDs are present
    assert str(high_old.id) in body
    assert str(normal_new.id) in body


def test_pending_pagination_per_page(admin_client, db):
    """?per_page=25 paginates to 25 rows in the page object.

    Args:
        admin_client: Authenticated admin Django test client.
        db: pytest-django database fixture.
    """
    from datetime import datetime, timezone as dt_tz

    for i in range(30):
        g = Game.objects.create(
            id=f"task7_pag_{i}",
            white_username=f"w{i}", black_username=f"b{i}",
            played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
            time_control="",
        )
        AnalysisJob.objects.create(
            game=g, engine="stockfish",
            status=AnalysisJob.STATUS_PENDING,
            priority=AnalysisJob.PRIORITY_NORMAL,
        )

    resp = admin_client.get(reverse("analysis:queue_stockfish") + "?per_page=25")
    assert resp.status_code == 200
    page = resp.context["pending_page"]
    assert len(page.object_list) == 25
    assert page.paginator.num_pages == 2


def test_pending_pagination_page_two(admin_client, db):
    """?page=2 with per_page=25 returns the second page.

    Args:
        admin_client: Authenticated admin Django test client.
        db: pytest-django database fixture.
    """
    from datetime import datetime, timezone as dt_tz

    for i in range(30):
        g = Game.objects.create(
            id=f"task7_p2_{i}",
            white_username=f"w{i}", black_username=f"b{i}",
            played_at=datetime(2026, 5, 10, tzinfo=dt_tz.utc),
            time_control="",
        )
        AnalysisJob.objects.create(
            game=g, engine="stockfish",
            status=AnalysisJob.STATUS_PENDING,
            priority=AnalysisJob.PRIORITY_NORMAL,
        )

    resp = admin_client.get(
        reverse("analysis:queue_stockfish") + "?per_page=25&page=2"
    )
    assert resp.status_code == 200
    page = resp.context["pending_page"]
    assert page.number == 2
    assert len(page.object_list) == 5
