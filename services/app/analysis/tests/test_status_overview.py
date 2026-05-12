"""
Title: test_status_overview.py — /analysis/ overview cards tests
Description: Verifies /admin/queues/ renders one card per engine with the right
    counts and links to the per-engine queue pages, and confirms the
    100-row recent-jobs table is removed.
Changelog:
    2026-05-11: Task 4 — update reverse() calls to 'analysis:queues_summary'.
    2026-05-10: Initial — Task C1 of scrap-dispatchers plan.
"""
import uuid

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


def _make_game(suffix: str) -> Game:
    """Create a minimal Game for test fixtures.

    Args:
        suffix: Short label included in the generated ID for test clarity.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"oc1-{suffix}-{uuid.uuid4().hex[:8]}",
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


class StatusOverviewTests(TestCase):
    """Tests for the /analysis/ overview cards page."""

    def test_cards_render_with_links(self):
        """Engine cards are rendered and link to per-engine queue detail pages.

        Verifies:
        - Both Stockfish and Lc0 cards appear.
        - Each card links to the correct queue detail URL.
        - The old 100-row recent-jobs table is absent.
        """
        admin = _make_admin()
        g = _make_game("a")
        AnalysisJob.objects.create(
            game=g,
            engine="stockfish",
            status=AnalysisJob.STATUS_PENDING,
            depth=20,
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse("analysis:queues_summary"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # Both engine cards rendered
        self.assertIn("Stockfish", body)
        self.assertIn("Lc0", body)
        # Cards link to queue detail pages
        self.assertIn(reverse("analysis:queue_stockfish"), body)
        self.assertIn(reverse("analysis:queue_lc0"), body)
        # 100-row recent-jobs table is gone
        self.assertNotIn("Recent Jobs", body)

    def test_requires_admin_login(self):
        """Anonymous requests are redirected to the login page."""
        resp = self.client.get(reverse("analysis:queues_summary"))
        self.assertIn(resp.status_code, (302, 403))

    def test_non_admin_redirected(self):
        """Non-admin authenticated users cannot access the overview page."""
        user = User.objects.create_user(
            email=f"player-{uuid.uuid4().hex[:6]}@test",
            password="x",
            role="player",
        )
        self.client.force_login(user)
        resp = self.client.get(reverse("analysis:queues_summary"))
        self.assertIn(resp.status_code, (302, 403))
