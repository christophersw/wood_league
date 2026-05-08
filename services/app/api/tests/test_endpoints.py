"""
Title: test_endpoints.py — API endpoint tests
Description:
    Tests for checkout, complete, fail, and heartbeat endpoints.

Changelog:
    2026-05-06 (#15): Created endpoint integration tests
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import User
from games.models import Game
from analysis.models import AnalysisJob, GameAnalysis, MoveAnalysis
from api.models import WorkerAPIKey


class JobCheckoutTests(TestCase):
    """Test POST /api/v1/jobs/checkout/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='worker', worker_name='worker', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        
        self.game = Game.objects.create(
            id='test-game',
            white_username='A',
            black_username='B',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. e4 e5'
        )

    def test_checkout_returns_pending_jobs(self):
        """Checkout endpoint returns pending jobs."""
        job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        
        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 1,
            'worker_id': 'my-worker',
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['jobs']), 1)
        self.assertEqual(data['jobs'][0]['id'], job.id)

    def test_checkout_claimed_job_sets_worker_id(self):
        """Checkout claims the job and sets worker_id."""
        AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        
        self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 1,
            'worker_id': 'my-worker',
        })
        
        job = AnalysisJob.objects.get()
        self.assertEqual(job.status, AnalysisJob.STATUS_RUNNING)
        self.assertEqual(job.worker_id, 'my-worker')

    def test_checkout_respects_batch_size(self):
        """Checkout respects batch_size parameter."""
        for _ in range(5):
            AnalysisJob.objects.create(
                game=self.game, engine='stockfish',
                status=AnalysisJob.STATUS_PENDING,
            )
        
        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 2,
            'worker_id': 'worker-1',
        })
        
        data = response.json()
        self.assertEqual(len(data['jobs']), 2)

    def test_checkout_priority_order(self):
        """Checkout returns jobs in priority order."""
        j1 = AnalysisJob.objects.create(
            game=self.game, engine='stockfish',
            priority=1, status=AnalysisJob.STATUS_PENDING,
        )
        j2 = AnalysisJob.objects.create(
            game=self.game, engine='stockfish',
            priority=2, status=AnalysisJob.STATUS_PENDING,
        )
        
        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 2,
            'worker_id': 'worker-1',
        })
        
        data = response.json()
        self.assertEqual(data['jobs'][0]['id'], j2.id)  # Higher priority first
        self.assertEqual(data['jobs'][1]['id'], j1.id)

    def test_checkout_specific_game_claims_only_requested_job(self):
        """Checkout claims only the requested game when game_id is provided."""
        target_game = Game.objects.create(
            id='requested-game',
            white_username='C',
            black_username='D',
            played_at=timezone.now(),
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

        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 10,
            'worker_id': 'my-worker',
            'game_id': target_game.id,
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['jobs']), 1)
        self.assertEqual(data['jobs'][0]['id'], target_job.id)

    def test_checkout_specific_game_denied_when_analysis_already_done(self):
        """Checkout returns 409 when requested game already has completed analysis."""
        target_game = Game.objects.create(
            id='already-analyzed-game',
            white_username='C',
            black_username='D',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. d4 d5',
        )
        AnalysisJob.objects.create(
            game=target_game,
            engine='stockfish',
            status=AnalysisJob.STATUS_PENDING,
        )
        GameAnalysis.objects.create(game=target_game)

        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 1,
            'worker_id': 'my-worker',
            'game_id': target_game.id,
        })

        self.assertEqual(response.status_code, 409)
        self.assertIn('already completed', response.json()['error'])

    def test_checkout_specific_game_denied_when_already_claimed(self):
        """Checkout returns 409 when requested game is already running."""
        target_game = Game.objects.create(
            id='already-claimed-game',
            white_username='C',
            black_username='D',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. d4 d5',
        )
        AnalysisJob.objects.create(
            game=target_game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            worker_id='other-worker',
        )

        response = self.client.post('/api/v1/jobs/checkout/', {
            'engine': 'stockfish',
            'batch_size': 1,
            'worker_id': 'my-worker',
            'game_id': target_game.id,
        })

        self.assertEqual(response.status_code, 409)
        self.assertIn('already claimed', response.json()['error'])


class JobCompleteTests(TestCase):
    """Test POST /api/v1/jobs/<id>/complete/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='worker', worker_name='worker', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        
        self.game = Game.objects.create(
            id='test-game',
            white_username='A',
            black_username='B',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. e4 e5'
        )
        self.job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            worker_id='my-worker',
            claimed_by_key_prefix=self.api_key.prefix,
        )

    def test_complete_stockfish_job_writes_results(self):
        """Complete endpoint writes GameAnalysis and MoveAnalysis."""
        payload = {
            'worker_id': 'my-worker',
            'engine_depth': 20,
            'white_accuracy': 95.5,
            'black_accuracy': 87.2,
            'white_acpl': 25.0,
            'black_acpl': 35.5,
            'white_blunders': 0,
            'white_mistakes': 1,
            'white_inaccuracies': 2,
            'black_blunders': 1,
            'black_mistakes': 2,
            'black_inaccuracies': 3,
            'moves': [
                {
                    'ply': 1,
                    'san': 'e4',
                    'fen': 'rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1',
                    'cp_eval': 35,
                    'cpl': 0,
                    'best_move': 'e4',
                    'classification': 'Best',
                }
            ],
        }
        
        response = self.client.post(f'/api/v1/jobs/{self.job.id}/complete/', payload)
        
        self.assertEqual(response.status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.STATUS_COMPLETED)
        
        analysis = GameAnalysis.objects.get(game=self.game)
        self.assertEqual(analysis.white_accuracy, 95.5)
        
        move = MoveAnalysis.objects.get(game=self.game)
        self.assertEqual(move.ply, 1)

    def test_complete_wrong_worker_returns_404(self):
        """Complete with wrong worker_id returns 404."""
        response = self.client.post(f'/api/v1/jobs/{self.job.id}/complete/', {
            'worker_id': 'wrong-worker',
            'engine_depth': 20,
            'white_accuracy': 95.5,
            'black_accuracy': 87.2,
            'white_acpl': 25.0,
            'black_acpl': 35.5,
            'white_blunders': 0,
            'white_mistakes': 0,
            'white_inaccuracies': 0,
            'black_blunders': 0,
            'black_mistakes': 0,
            'black_inaccuracies': 0,
            'moves': [],
        })
        
        self.assertEqual(response.status_code, 404)

    def test_complete_already_completed_returns_404(self):
        """Completing an already-completed job returns 404."""
        self.job.status = AnalysisJob.STATUS_COMPLETED
        self.job.save()
        
        response = self.client.post(f'/api/v1/jobs/{self.job.id}/complete/', {
            'worker_id': 'my-worker',
            'engine_depth': 20,
            'white_accuracy': 95.5,
            'black_accuracy': 87.2,
            'white_acpl': 25.0,
            'black_acpl': 35.5,
            'white_blunders': 0,
            'white_mistakes': 0,
            'white_inaccuracies': 0,
            'black_blunders': 0,
            'black_mistakes': 0,
            'black_inaccuracies': 0,
            'moves': [],
        })
        
        self.assertEqual(response.status_code, 404)


class JobFailTests(TestCase):
    """Test POST /api/v1/jobs/<id>/fail/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='worker', worker_name='worker', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)
        
        self.game = Game.objects.create(
            id='test-game',
            white_username='A',
            black_username='B',
            played_at=timezone.now(),
            time_control='rapid',
            pgn='1. e4 e5'
        )
        self.job = AnalysisJob.objects.create(
            game=self.game,
            engine='stockfish',
            status=AnalysisJob.STATUS_RUNNING,
            worker_id='my-worker',
            claimed_by_key_prefix=self.api_key.prefix,
        )

    def test_fail_job_requeues(self):
        """Fail endpoint requeues job when under max retries."""
        response = self.client.post(f'/api/v1/jobs/{self.job.id}/fail/', {
            'worker_id': 'my-worker',
            'error': 'Out of memory',
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'requeued')
        
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, AnalysisJob.STATUS_PENDING)
        self.assertEqual(self.job.retry_count, 1)


class HeartbeatTests(TestCase):
    """Test POST /api/v1/heartbeat/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='worker', worker_name='worker', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

    def test_heartbeat_creates_worker_heartbeat(self):
        """Heartbeat endpoint creates or updates WorkerHeartbeat."""
        response = self.client.post('/api/v1/heartbeat/', {
            'worker_id': 'my-worker',
            'engine': 'stockfish',
            'status_message': 'idle',
        })
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')


class QueueStatusTests(TestCase):
    """Test GET /api/v1/jobs/status/"""

    def setUp(self):
        """Create test data."""
        self.client = APIClient()
        self.user = User.objects.create_user(email='test@test.local', password='pass')
        self.api_key, self.raw_key = WorkerAPIKey.objects.create_key(
            name='worker', worker_name='worker', created_by=self.user
        )
        self.client.credentials(HTTP_X_API_KEY=self.raw_key)

    def test_queue_status_returns_counts(self):
        """Queue status endpoint returns job counts by engine and status."""
        response = self.client.get('/api/v1/jobs/status/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('queue', data)
