"""
Title: test_views_queue.py — Queue detail page tests
Description: Verifies /queue/<engine>/ renders pending AnalysisJobs for the
    engine, requires admin auth, and excludes other engines' jobs.
Changelog:
    2026-05-10: Initial — Task B1 of scrap-dispatchers plan.
"""
import uuid

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
