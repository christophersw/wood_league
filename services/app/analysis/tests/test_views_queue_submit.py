"""
Title: test_views_queue_submit.py — Bulk RunPod submit endpoint tests
Description: Happy path, partial failure, skip-when-not-pending, engine-filter
    protection, and concurrent-submit race for POST /admin/queue/<engine>/submit/.
Changelog:
    2026-05-10: Initial — Task B2 of scrap-dispatchers plan.
    2026-05-11: Add concurrent-submit race test (issue #16).
"""
import uuid
from unittest.mock import patch

import psycopg2
from django.db import connection
from django.test import TestCase, TransactionTestCase
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


class ConcurrentSubmitRaceTests(TransactionTestCase):
    """Race test for the per-job ``SELECT FOR UPDATE SKIP LOCKED`` in queue_submit.

    Simulates the worst-case race deterministically: a separate raw psycopg2
    connection opens its own transaction and locks the candidate row with
    ``SELECT ... FOR UPDATE``. The view is then invoked through the Django
    test client. Because ``queue_submit`` uses ``skip_locked=True``, its
    ``select_for_update`` must return ``None`` for the held row — the job
    is counted as skipped and ``submit_job_to_runpod`` is never called. After
    releasing the external lock, a second invocation of the view should win
    the lock cleanly and submit the job exactly once.

    Uses ``TransactionTestCase`` (instead of ``TestCase``) so each ORM
    operation commits — the external psycopg2 connection has to see the
    seeded row from another transaction.
    """

    def _connection_params(self) -> dict:
        """Return psycopg2 connect kwargs for the active test database.

        Returns:
            dict: Connection parameters (host, port, dbname, user, password)
                pointing at the Django test database for the default alias.
        """
        # ``connection.settings_dict`` reflects the active test DB name
        # (e.g. ``test_railway``), whereas ``settings.DATABASES`` still holds
        # the original production NAME from DATABASE_URL.
        config = connection.settings_dict
        return {
            "host": config.get("HOST") or "localhost",
            "port": config.get("PORT") or 5432,
            "dbname": config["NAME"],
            "user": config.get("USER"),
            "password": config.get("PASSWORD"),
        }

    def _make_pending_job(self) -> int:
        """Create one pending Stockfish AnalysisJob and return its primary key.

        Returns:
            int: The primary key of the created AnalysisJob row.
        """
        game = Game.objects.create(
            id=f"qb2-race-{uuid.uuid4().hex[:8]}",
            played_at=timezone.now(),
            time_control="600",
            pgn="1. e4 *",
        )
        job = AnalysisJob.objects.create(
            game=game, engine="stockfish",
            status=AnalysisJob.STATUS_PENDING, depth=20,
        )
        return job.id

    def test_skip_locked_prevents_double_submit_to_runpod(self):
        """A row locked by a parallel transaction must be skipped, not submitted.

        Holds a ``SELECT ... FOR UPDATE`` on the candidate row via a separate
        psycopg2 connection, then invokes ``queue_submit`` through the Django
        test client. Because the view's ``select_for_update(skip_locked=True)``
        encounters a locked row, it must:
          * return immediately with ``job is None``,
          * count the job as skipped,
          * never call ``submit_job_to_runpod``.

        After releasing the external lock, a second call must successfully
        submit the still-pending job, proving the lock didn't permanently
        corrupt state. ``submit_job_to_runpod`` is therefore called exactly
        once across both invocations — no double-submission to RunPod.
        """
        admin = User.objects.create_user(
            email=f"admin-{uuid.uuid4().hex[:6]}@test",
            password="x",  # noqa: S106 — test-only password
            role="admin",
        )
        self.client.force_login(admin)
        jid = self._make_pending_job()

        submit_calls: list[int] = []

        def fake_submit(job):
            """Record each call; return a unique fake RunPod job id."""
            submit_calls.append(job.id)
            return f"rp-{job.id}"

        # Open a raw connection and lock the row from a parallel transaction.
        parallel = psycopg2.connect(**self._connection_params())
        parallel.autocommit = False
        try:
            with parallel.cursor() as cur:
                cur.execute(
                    "SELECT id FROM analysis_jobs WHERE id = %s FOR UPDATE",
                    (jid,),
                )
                self.assertEqual(cur.fetchone()[0], jid)

                with patch("analysis.views_queue.submit_job_to_runpod",
                           side_effect=fake_submit):
                    resp = self.client.post(
                        reverse("analysis:queue_submit", args=["stockfish"]),
                        {"job_ids": [str(jid)]},
                        secure=True,
                    )

            self.assertEqual(resp.status_code, 200)
            self.assertEqual(
                submit_calls, [],
                "submit_job_to_runpod must not run while the row is locked",
            )
            still_pending = AnalysisJob.objects.get(pk=jid)
            self.assertEqual(still_pending.status, AnalysisJob.STATUS_PENDING)
            self.assertIsNone(still_pending.runpod_job_id)
        finally:
            parallel.rollback()
            parallel.close()

        # Now the lock is released; the next invocation must submit cleanly
        # and exactly once — proving no double-submission across the race.
        with patch("analysis.views_queue.submit_job_to_runpod",
                   side_effect=fake_submit):
            resp = self.client.post(
                reverse("analysis:queue_submit", args=["stockfish"]),
                {"job_ids": [str(jid)]},
                secure=True,
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            submit_calls, [jid],
            "submit_job_to_runpod must run exactly once across both attempts",
        )
        submitted = AnalysisJob.objects.get(pk=jid)
        self.assertEqual(submitted.status, AnalysisJob.STATUS_SUBMITTED)
        self.assertEqual(submitted.runpod_job_id, f"rp-{jid}")
