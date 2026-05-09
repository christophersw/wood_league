"""Tests for wood_league_shared.worker_client."""
import httpx
import pytest

from wood_league_shared.worker_client import WorkerClient, WorkerClientError
from wood_league_shared.worker_client.models import Job


class TestJob:
    def test_job_fields(self):
        job = Job(id=1, game_id='g1', pgn='1. e4', engine='stockfish', depth=20, nodes=None)
        assert job.id == 1
        assert job.game_id == 'g1'
        assert job.nodes is None


class TestWorkerClientCheckout:
    def setup_method(self):
        self.client = WorkerClient(base_url='http://api.test', api_key='test-key')

    def test_checkout_returns_jobs(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(200, json={
                'jobs': [{
                    'id': 1, 'game_id': 'g1', 'pgn': '1. e4',
                    'engine': 'stockfish', 'depth': 20, 'nodes': None,
                    'worker_id': 'w1', 'claimed_by_key_prefix': 'abc',
                }]
            })
        )
        jobs = self.client.checkout(engine='stockfish', worker_id='w1')
        assert len(jobs) == 1
        assert jobs[0].id == 1
        assert jobs[0].pgn == '1. e4'

    def test_checkout_returns_empty_on_no_jobs(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(200, json={'jobs': []})
        )
        jobs = self.client.checkout(engine='stockfish', worker_id='w1')
        assert jobs == []

    def test_checkout_raises_on_5xx(self, respx_mock):
        route = respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(500, text='error')
        )
        with pytest.raises(WorkerClientError):
            self.client.checkout(engine='stockfish', worker_id='w1')
        assert route.call_count == 3

    def test_checkout_retries_on_network_error(self, respx_mock):
        route = respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            side_effect=httpx.ConnectError('connection refused')
        )
        with pytest.raises(WorkerClientError):
            self.client.checkout(engine='stockfish', worker_id='w1')
        assert route.call_count == 3

    def test_checkout_raises_on_4xx(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/checkout/').mock(
            return_value=httpx.Response(401, json={'detail': 'not authenticated'})
        )
        with pytest.raises(WorkerClientError):
            self.client.checkout(engine='stockfish', worker_id='w1')


class TestWorkerClientFail:
    def setup_method(self):
        self.client = WorkerClient(base_url='http://api.test', api_key='test-key')

    def test_fail_returns_outcome(self, respx_mock):
        respx_mock.post('http://api.test/api/v1/jobs/1/fail/').mock(
            return_value=httpx.Response(200, json={'status': 'requeued'})
        )
        outcome = self.client.fail(job_id=1, worker_id='w1', error='boom')
        assert outcome == 'requeued'
