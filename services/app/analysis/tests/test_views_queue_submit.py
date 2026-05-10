"""
Title: test_views_queue_submit.py — Bulk RunPod submit endpoint tests
Description: Happy path, partial failure, skip-when-not-pending, and engine-filter
    protection for POST /admin/queue/<engine>/submit/.
Changelog:
    2026-05-10: Initial — Task B2 of scrap-dispatchers plan.
"""
import uuid
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from analysis.models import AnalysisJob
from games.models import Game


def _make_game(suffix: str) -> Game:
    """Create a minimal Game instance with a unique ID.

    Args:
        suffix: String suffix for the game ID to aid test traceability.

    Returns:
        Game: A saved Game instance.
    """
    return Game.objects.create(
        id=f"qb2-{suffix}-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 *",
    )


def _make_admin() -> User:
    """Create a User with admin role.

    Returns:
        User: A saved admin User instance.
    """
    return User.objects.create_user(
        email=f"admin-{uuid.uuid4().hex[:6]}@test", password="x", role="admin"
    )


class BulkSubmitTests(TestCase):
    """Tests for POST /admin/queue/<engine>/submit/ bulk-submit endpoint."""

    def setUp(self):
        """Create an admin user and log them in for each test."""
        self.admin = _make_admin()
        self.client.force_login(self.admin)

    def _make_pending(self, n: int, engine: str = "stockfish") -> list[int]:
        """Create n pending AnalysisJob rows for the given engine.

        Args:
            n: Number of jobs to create.
            engine: Engine name for the jobs.

        Returns:
            list[int]: List of created AnalysisJob primary keys.
        """
        ids = []
        for i in range(n):
            g = _make_game(f"{engine}-{i}")
            j = AnalysisJob.objects.create(
                game=g, engine=engine, status=AnalysisJob.STATUS_PENDING, depth=20
            )
            ids.append(j.id)
        return ids

    def test_happy_path_three_submitted(self):
        """All three pending jobs should transition to submitted with runpod_job_id set."""
        ids = self._make_pending(3)
        with patch("analysis.views_queue.submit_job_to_runpod",
                   side_effect=lambda job: f"rp-{job.id}"):
            resp = self.client.post(
                reverse("analysis:queue_submit", args=["stockfish"]),
                {"job_ids": [str(i) for i in ids]},
            )
        self.assertEqual(resp.status_code, 200)
        for jid in ids:
            j = AnalysisJob.objects.get(pk=jid)
            self.assertEqual(j.status, AnalysisJob.STATUS_SUBMITTED)
            self.assertEqual(j.runpod_job_id, f"rp-{jid}")

    def test_partial_failure_records_last_error(self):
        """Failed job stays pending with last_error set; successful job is submitted."""
        ids = self._make_pending(2)

        def fake(job):
            if job.id == ids[1]:
                raise RuntimeError("rp down")
            return f"rp-{job.id}"

        with patch("analysis.views_queue.submit_job_to_runpod", side_effect=fake):
            self.client.post(
                reverse("analysis:queue_submit", args=["stockfish"]),
                {"job_ids": [str(i) for i in ids]},
            )

        ok = AnalysisJob.objects.get(pk=ids[0])
        bad = AnalysisJob.objects.get(pk=ids[1])
        self.assertEqual(ok.status, AnalysisJob.STATUS_SUBMITTED)
        self.assertEqual(bad.status, AnalysisJob.STATUS_PENDING)
        self.assertIn("rp down", bad.last_error or "")
        self.assertIsNotNone(bad.last_error_at)

    def test_already_submitted_is_skipped(self):
        """Jobs that are already submitted must be skipped without calling submit_job_to_runpod."""
        ids = self._make_pending(1)
        AnalysisJob.objects.filter(pk=ids[0]).update(status=AnalysisJob.STATUS_SUBMITTED)
        with patch("analysis.views_queue.submit_job_to_runpod") as mock_sub:
            self.client.post(
                reverse("analysis:queue_submit", args=["stockfish"]),
                {"job_ids": [str(ids[0])]},
            )
        mock_sub.assert_not_called()

    def test_wrong_engine_jobs_protected(self):
        """Submitting to /queue/stockfish/ must not touch lc0 jobs."""
        sf_ids = self._make_pending(1, engine="stockfish")
        lc_ids = self._make_pending(1, engine="lc0")
        with patch("analysis.views_queue.submit_job_to_runpod",
                   side_effect=lambda job: f"rp-{job.id}") as mock_sub:
            self.client.post(
                reverse("analysis:queue_submit", args=["stockfish"]),
                {"job_ids": [str(sf_ids[0]), str(lc_ids[0])]},
            )
        self.assertEqual(mock_sub.call_count, 1)
        self.assertEqual(
            AnalysisJob.objects.get(pk=lc_ids[0]).status, AnalysisJob.STATUS_PENDING
        )
