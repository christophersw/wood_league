"""
Title: client.py — HTTP client for the Django analysis worker API
Description:
    Wraps the Django REST API endpoints used by analysis workers.
    All methods raise WorkerClientError on failure. 5xx responses
    are retried up to 3 times with exponential backoff; 4xx are not.

Changelog:
    2026-05-08: Created
    2026-05-10: Copied from packages/shared to make local_worker self-contained for PyPI
    2026-05-17 (#128): heartbeat carries batch_total/batch_processed/session_started_at.
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


def _maybe_raise_needs_calibration(resp: httpx.Response) -> None:
    """Inspect a 409 response and raise NeedsCalibrationError when it applies.

    Args:
        resp: The httpx Response under inspection. Non-409 responses and
            409 responses that aren't NEEDS_CALIBRATION are no-ops.

    Raises:
        NeedsCalibrationError: When the body parses as JSON with
            ``error == "NEEDS_CALIBRATION"``.
    """
    if resp.status_code != 409:
        return
    try:
        body = resp.json()
    except ValueError:
        return
    if not isinstance(body, dict) or body.get("error") != "NEEDS_CALIBRATION":
        return
    raise NeedsCalibrationError(
        network_name=body["network_name"],
        settings_hash=body["settings_hash"],
        sampler_settings=body["sampler_settings"],
        sampler_version=body["sampler_version"],
    )


class WorkerClientError(Exception):
    """Raised when the API returns an error response."""


class NeedsCalibrationError(WorkerClientError):
    """Raised when the app rejects an lc0 checkout pending calibration.

    Issue #161 Phase B: the API responds 409 with
    ``{"error": "NEEDS_CALIBRATION", "network_name": ..., "settings_hash": ...,
    "sampler_settings": {...}, "sampler_version": ...}``. The worker handles
    this by running the calibration sampler with the supplied settings,
    POSTing the result, then retrying checkout.
    """

    def __init__(
        self,
        *,
        network_name: str,
        settings_hash: str,
        sampler_settings: dict,
        sampler_version: str,
    ) -> None:
        """Capture the 409 body so the run loop can drive the sampler.

        Args:
            network_name: Resolved lc0 network identifier.
            settings_hash: Canonical sampler-settings hash to echo on POST.
            sampler_settings: Canonical settings dict the worker must use.
            sampler_version: Sampler-version tag from the app.
        """
        super().__init__(f"NEEDS_CALIBRATION for {network_name}")
        self.network_name = network_name
        self.settings_hash = settings_hash
        self.sampler_settings = sampler_settings
        self.sampler_version = sampler_version


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
            _maybe_raise_needs_calibration(resp)
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
        network_name: str = '',
    ) -> list[Job]:
        """Claim up to batch_size pending analysis jobs for the given engine.

        Args:
            engine: 'stockfish' or 'lc0'.
            worker_id: Unique worker identifier (hostname recommended).
            batch_size: Number of jobs to claim (default 1).
            game_id: Optional specific game to claim.
            dispatch_mode: 'pull' for local workers; 'runpod' for the dispatcher.
            network_name: For lc0 only: resolved network identifier. Sent so
                the app can pre-flight NetworkCalibration (#161 Phase B); a
                blank value preserves the legacy call shape.

        Returns:
            List of Job dataclasses (empty if queue is empty).

        Raises:
            NeedsCalibrationError: When the app returns 409 NEEDS_CALIBRATION
                because the supplied lc0 network has no calibration row.
            WorkerClientError: For any other 4xx / 5xx-after-retries failure.
        """
        payload: dict[str, Any] = {
            'engine': engine,
            'worker_id': worker_id,
            'batch_size': batch_size,
            'dispatch_mode': dispatch_mode,
        }
        if game_id is not None:
            payload['game_id'] = game_id
        if network_name:
            payload['network_name'] = network_name
        data = self._post('/api/v1/jobs/checkout/', payload)
        return [
            Job(
                id=j['id'],
                game_id=j['game_id'],
                pgn=j['pgn'],
                engine=j['engine'],
                depth=j['depth'],
                nodes=j.get('nodes'),
                white_rating=j.get('white_rating'),
                black_rating=j.get('black_rating'),
                draw_rate_reference=j.get('draw_rate_reference'),
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

    def submit_network_calibration(
        self,
        *,
        network_name: str,
        settings_hash: str,
        draw_rate_reference: float,
        sample_size: int,
        sem: float,
        sampler_version: str,
        worker_id: str,
    ) -> dict:
        """Submit a completed lc0 draw-rate measurement (#161 Phase A).

        Args:
            network_name: Resolved lc0 network identifier.
            settings_hash: Lowercase hex sha256 of canonical sampler settings.
            draw_rate_reference: Measured draw probability in (0.001, 0.999).
            sample_size: Positions sampled before convergence/cap.
            sem: Standard error of the mean achieved by the sampler.
            sampler_version: Echoed from settings.WL_LC0_DRAW_RATE_SAMPLER_VERSION.
            worker_id: Unique worker identifier (recorded on the row).

        Returns:
            Parsed JSON body. ``created`` is True if this writer was first,
            False if an existing row was kept (idempotent no-op).

        Raises:
            WorkerClientError: On 4xx, 5xx after retries, or network failure.
        """
        return self._post(
            '/api/v1/network_calibrations/',
            {
                'network_name': network_name,
                'settings_hash': settings_hash,
                'draw_rate_reference': draw_rate_reference,
                'sample_size': sample_size,
                'sem': sem,
                'sampler_version': sampler_version,
                'worker_id': worker_id,
            },
        )

    def heartbeat(
        self, *, worker_id: str, engine: str, status_message: str = '',
        batch_total: int | None = None, batch_processed: int = 0,
        session_started_at: str | None = None,
    ) -> None:
        """Send a worker heartbeat to indicate the worker is alive.

        Args:
            worker_id: Unique worker identifier.
            engine: 'stockfish' or 'lc0'.
            status_message: Human-readable status string.
            batch_total: max_jobs run cap (M in N/M); ``None`` = unlimited.
            batch_processed: Jobs completed so far this session (N).
            session_started_at: ISO-8601 wall-clock start of this run, for
                the dashboard's billable time/game metric.

        Backward compatible: the batch fields are only added to the
        payload when supplied, so older servers ignore them and newer
        callers that omit them behave as before.
        """
        payload: dict[str, object] = {
            'worker_id': worker_id,
            'engine': engine,
            'status_message': status_message,
        }
        if batch_total is not None:
            payload['batch_total'] = batch_total
        if batch_processed:
            payload['batch_processed'] = batch_processed
        if session_started_at is not None:
            payload['session_started_at'] = session_started_at
        try:
            self._post('/api/v1/heartbeat/', payload)
        except WorkerClientError:
            log.warning('Heartbeat failed — continuing')
