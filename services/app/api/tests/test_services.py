"""
Title: test_services.py — Service layer unit tests
Description:
    Tests for analysis/services/jobs.py functions: recover_stale_jobs,
    claim_jobs, complete_stockfish_job, complete_lc0_job, fail_job.

Changelog:
    2026-05-06 (#15): Created service layer unit tests
"""
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from django.conf import settings
from games.models import Game
from analysis.models import AnalysisJob, GameAnalysis, MoveAnalysis
from analysis.services.jobs import (
    recover_stale_jobs,
    claim_jobs,
    complete_stockfish_job,
    complete_lc0_job,
    fail_job,
    JobCheckoutDenied,
)


class StaleJobRecoveryTests(TestCase):
    """Test recover_stale_jobs function."""

    def setUp(self):
        """Create test game and jobs."""
        self.game = Game.objects.create(
            id='test-game-1',
            white_username='Alice',
            black_username='Bob',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. e4 e5',
        )

    def test_recover_stale_running_jobs(self):
        """Jobs stuck in 'running' > STALE_JOB_TIMEOUT_MINUTES are reset."""
        now = timezone.now()
        old_time = now - timedelta(minutes=settings.STALE_JOB_TIMEOUT_MINUTES + 5)
        
        job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            started_at=old_time,
            worker_id='worker-1',
            claimed_by_key_prefix='abc12345',
            claimed_at=old_time,
        )
        
        recovered = recover_stale_jobs('stockfish')
        
        self.assertEqual(recovered, 1)
        job.refresh_from_db()
        self.assertEqual(job.status, AnalysisJob.STATUS_PENDING)
        self.assertIsNone(job.worker_id)
        self.assertIsNone(job.claimed_by_key_prefix)
        self.assertIsNone(job.claimed_at)

    def test_no_recover_recent_running_jobs(self):
        """Jobs running < STALE_JOB_TIMEOUT_MINUTES are not reset."""
        now = timezone.now()
        recent_time = now - timedelta(minutes=5)
        
        job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            started_at=recent_time,
            worker_id='worker-1',
        )
        
        recovered = recover_stale_jobs('stockfish')
        
        self.assertEqual(recovered, 0)
        job.refresh_from_db()
        self.assertEqual(job.status, AnalysisJob.STATUS_RUNNING)


class ClaimJobsTests(TestCase):
    """Test claim_jobs function."""

    def setUp(self):
        """Create test game and jobs."""
        self.game = Game.objects.create(
            id='test-game-2',
            white_username='Alice',
            black_username='Bob',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. e4 e5',
        )

    def test_claim_pending_jobs(self):
        """claim_jobs returns pending jobs in priority order."""
        j1 = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            priority=1,
            status=AnalysisJob.STATUS_PENDING,
        )
        j2 = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            priority=2,
            status=AnalysisJob.STATUS_PENDING,
        )
        
        jobs = claim_jobs(
            engine='stockfish',
            batch_size=10,
            worker_id='my-worker',
            key_prefix='abc12345',
        )
        
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].id, j2.id)  # Higher priority first
        self.assertEqual(jobs[1].id, j1.id)

    def test_claim_respects_batch_size(self):
        """claim_jobs claims only up to batch_size."""
        for i in range(5):
            AnalysisJob.objects.create(
                game=self.game,
                engine='stockfish',
                priority=0,
                status=AnalysisJob.STATUS_PENDING,
            )
        
        jobs = claim_jobs(
            engine='stockfish',
            batch_size=2,
            worker_id='worker-1',
        )
        
        self.assertEqual(len(jobs), 2)

    def test_claimed_job_fields_set(self):
        """Claimed jobs have status, worker_id, claimed_at, claimed_by_key_prefix set."""
        AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        
        before = timezone.now()
        jobs = claim_jobs(
            engine='stockfish',
            batch_size=1,
            worker_id='my-worker',
            key_prefix='xyz99999',
        )
        after = timezone.now()
        
        job = jobs[0]
        self.assertEqual(job.status, AnalysisJob.STATUS_RUNNING)
        self.assertEqual(job.worker_id, 'my-worker')
        self.assertEqual(job.claimed_by_key_prefix, 'xyz99999')
        self.assertGreaterEqual(job.claimed_at, before)
        self.assertLessEqual(job.claimed_at, after)

    def test_claim_specific_game_claims_requested_job(self):
        """claim_jobs claims only the requested game when game_id is provided."""
        target_game = Game.objects.create(
            id='requested-game',
            white_username='Carol',
            black_username='Dave',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. d4 d5',
        )
        target_job = AnalysisJob.objects.create(
            game=target_game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )

        jobs = claim_jobs(
            engine='stockfish',
            batch_size=10,
            worker_id='my-worker',
            key_prefix='abc12345',
            game_id=target_game.id,
        )

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].id, target_job.id)

    def test_claim_specific_game_denied_when_analysis_exists(self):
        """claim_jobs denies request when analysis already exists for requested game."""
        target_game = Game.objects.create(
            id='already-analyzed-game',
            white_username='Carol',
            black_username='Dave',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. d4 d5',
        )
        AnalysisJob.objects.create(
            game=target_game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        GameAnalysis.objects.create(game=target_game)

        with self.assertRaises(JobCheckoutDenied):
            claim_jobs(
                engine='stockfish',
                batch_size=1,
                worker_id='my-worker',
                key_prefix='abc12345',
                game_id=target_game.id,
            )

    def test_claim_specific_game_denied_when_already_claimed(self):
        """claim_jobs denies request when requested game is already running."""
        target_game = Game.objects.create(
            id='already-claimed-game',
            white_username='Carol',
            black_username='Dave',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. d4 d5',
        )
        AnalysisJob.objects.create(
            game=target_game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            worker_id='other-worker',
        )

        with self.assertRaises(JobCheckoutDenied):
            claim_jobs(
                engine='stockfish',
                batch_size=1,
                worker_id='my-worker',
                key_prefix='abc12345',
                game_id=target_game.id,
            )


class FailJobTests(TestCase):
    """Test fail_job function."""

    def setUp(self):
        """Create test game and job."""
        self.game = Game.objects.create(
            id='test-game-3',
            white_username='Alice',
            black_username='Bob',
            played_at='2026-05-06T00:00:00Z',
            time_control='rapid',
            pgn='1. e4 e5',
        )
        self.job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            worker_id='worker-1',
            claimed_by_key_prefix='abc12345',
        )

    @override_settings(MAX_JOB_RETRIES=3)
    def test_fail_job_increments_retry_count(self):
        """fail_job increments retry_count."""
        self.assertEqual(self.job.retry_count, 0)
        
        result = fail_job(
            job_id=self.job.id,
            worker_id='worker-1',
            key_prefix='abc12345',
            error='Out of memory',
        )
        
        self.job.refresh_from_db()
        self.assertEqual(self.job.retry_count, 1)
        self.assertEqual(result, 'requeued')

    @override_settings(MAX_JOB_RETRIES=3)
    def test_fail_job_requeues_under_max(self):
        """fail_job requeues when retry_count < MAX_JOB_RETRIES."""
        result = fail_job(
            job_id=self.job.id,
            worker_id='worker-1',
            key_prefix='abc12345',
            error='Error 1',
        )
        
        self.assertEqual(result, 'requeued')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.STATUS_PENDING)
        self.assertIsNone(self.job.worker_id)

    @override_settings(MAX_JOB_RETRIES=3)
    def test_fail_job_marks_failed_at_max_retries(self):
        """fail_job marks job as failed when retry_count >= MAX_JOB_RETRIES."""
        self.job.retry_count = 2
        self.job.save()
        
        result = fail_job(
            job_id=self.job.id,
            worker_id='worker-1',
            key_prefix='abc12345',
            error='Error 3',
        )
        
        self.assertEqual(result, 'failed')
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.STATUS_FAILED)
        self.assertEqual(self.job.retry_count, 3)
