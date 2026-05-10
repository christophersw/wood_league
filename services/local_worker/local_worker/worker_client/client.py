"""
Title: client.py — HTTP client for the Django analysis worker API
Description:
    Wraps the Django REST API endpoints used by analysis workers.
    All methods raise WorkerClientError on failure. 5xx responses
    are retried up to 3 times with exponential backoff; 4xx are not.

Changelog:
    2026-05-08: Created
    2026-05-10: Copied from packages/shared to make local_worker self-contained for PyPI
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .models import Job

log = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BACKOFF = [1.0, 2.0, 4.0]


class WorkerClientError(Exception):
    """Raised when the API returns an error response."""


class WorkerClient:
    """HTTP client for the Wood League analysis worker API."""

    def __init__(self, *, base_url: str, api_key: str) -> None:
        """Initialise the client with a base URL and API key.

        Args:
            base_url: Root URL of the Django app, e.g. 'https://app.example.com'
            api_key: Raw API key sent in the X-Api-Key header
        """
        self._base = base_url.rstrip('/')
        self._http = httpx.Client(
            headers={'X-Api-Key': api_key, 'Content-Type': 'application/json'},
            timeout=30,
        )

    def _post(self, path: str, payload: dict) -> dict:
        """POST to the API with retry on 5xx. Raises WorkerClientError on failure.

        Args:
            path: URL path relative to base_url (e.g. '/api/v1/jobs/checkout/')
            payload: JSON-serializable dict to send as the request body

        Returns:
            Parsed JSON response dict

        Raises:
            WorkerClientError: On 4xx, 5xx after retries, or network failure
        """
        url = f'{self._base}{path}'
        last_exc: Exception | None = None
        for attempt, backoff in enumerate(_RETRY_BACKOFF, start=1):
            try:
                resp = self._http.post(url, json=payload)
            except httpx.RequestError as exc:
                last_exc = exc
                log.warning('Request error (attempt %d): %s', attempt, exc)
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                continue
            if resp.status_code < 400:
                return resp.json()
            if resp.status_code >= 500:
                last_exc = WorkerClientError(f'HTTP {resp.status_code}: {resp.text[:200]}')
                log.warning('5xx from API (attempt %d): %s', attempt, resp.status_code)
                if attempt < _MAX_RETRIES:
                    time.sleep(backoff)
                continue
            raise WorkerClientError(f'HTTP {resp.status_code}: {resp.text[:200]}')
        raise WorkerClientError(f'API unavailable after {_MAX_RETRIES} attempts') from last_exc

    def checkout(
        self,
        *,
        engine: str,
        worker_id: str,
        batch_size: int = 1,
        game_id: str | None = None,
        dispatch_mode: str = 'pull',
    ) -> list[Job]:
        """Claim up to batch_size pending analysis jobs for the given engine.

        Args:
            engine: 'stockfish' or 'lc0'
            worker_id: Unique worker identifier (hostname recommended)
            batch_size: Number of jobs to claim (default 1)
            game_id: Optional specific game to claim
            dispatch_mode: 'pull' for local workers; 'runpod' for the dispatcher

        Returns:
            List of Job dataclasses (empty if queue is empty)
        """
        payload: dict[str, Any] = {
            'engine': engine,
            'worker_id': worker_id,
            'batch_size': batch_size,
            'dispatch_mode': dispatch_mode,
        }
        if game_id is not None:
            payload['game_id'] = game_id
        data = self._post('/api/v1/jobs/checkout/', payload)
        return [
            Job(
                id=j['id'],
                game_id=j['game_id'],
                pgn=j['pgn'],
                engine=j['engine'],
                depth=j['depth'],
                nodes=j.get('nodes'),
            )
            for j in data.get('jobs', [])
        ]

    def complete_stockfish(self, *, job_id: int, worker_id: str, payload: dict) -> None:
        """Report successful Stockfish analysis.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            payload: Dict matching StockfishCompleteSerializer fields
        """
        self._post(
            f'/api/v1/jobs/{job_id}/complete/',
            {'engine': 'stockfish', 'worker_id': worker_id, **payload},
        )

    def complete_lc0(self, *, job_id: int, worker_id: str, payload: dict) -> None:
        """Report successful lc0 analysis.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            payload: Dict matching Lc0CompleteSerializer fields
        """
        self._post(
            f'/api/v1/jobs/{job_id}/complete/',
            {'engine': 'lc0', 'worker_id': worker_id, **payload},
        )

    def fail(self, *, job_id: int, worker_id: str, error: str) -> str:
        """Report job failure.

        Args:
            job_id: Django AnalysisJob.id
            worker_id: Same worker_id used at checkout
            error: Error message (truncated to 2000 chars server-side)

        Returns:
            'requeued' if the job will be retried, 'failed' if exhausted
        """
        data = self._post(
            f'/api/v1/jobs/{job_id}/fail/',
            {'worker_id': worker_id, 'error': error},
        )
        return data.get('status', 'failed')

    def heartbeat(self, *, worker_id: str, engine: str, status_message: str = '') -> None:
        """Send a worker heartbeat to indicate the worker is alive.

        Args:
            worker_id: Unique worker identifier
            engine: 'stockfish' or 'lc0'
            status_message: Human-readable status string
        """
        try:
            self._post('/api/v1/heartbeat/', {
                'worker_id': worker_id,
                'engine': engine,
                'status_message': status_message,
            })
        except WorkerClientError:
            log.warning('Heartbeat failed — continuing')
