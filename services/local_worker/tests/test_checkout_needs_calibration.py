"""
Title: test_checkout_needs_calibration.py — WorkerClient 409 NEEDS_CALIBRATION
Description:
    Issue #161 Phase B. The worker's HTTP client must surface the app's
    structured 409 ``NEEDS_CALIBRATION`` response as a typed exception
    carrying ``network_name``, ``settings_hash``, ``sampler_settings``, and
    ``sampler_version``. Other 4xx responses must still raise the generic
    ``WorkerClientError``.

    Successful 200 responses now expose ``draw_rate_reference`` on each
    returned ``Job`` dataclass.

Changelog:
    2026-05-19 (#161/B): Initial.
"""
from __future__ import annotations

import json

import httpx
import pytest

from local_worker.worker_client import (
    NeedsCalibrationError,
    WorkerClient,
    WorkerClientError,
)


def _make_client_with_handler(handler) -> WorkerClient:
    """Build a WorkerClient with a MockTransport calling ``handler``."""
    client = WorkerClient(base_url="https://app.test", api_key="k")
    client._http = httpx.Client(  # noqa: SLF001 — test-only injection
        headers={"X-Api-Key": "k", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
        timeout=5,
    )
    return client


_NEEDS_CALIBRATION_BODY = {
    "error": "NEEDS_CALIBRATION",
    "network_name": "BT4-1740",
    "settings_hash": "a" * 64,
    "sampler_settings": {
        "sem_target": 0.005,
        "nodes": 800,
        "max_positions": 10000,
        "sampler_version": "v1",
    },
    "sampler_version": "v1",
}


def test_checkout_raises_needs_calibration_on_409() -> None:
    """A 409 with NEEDS_CALIBRATION body raises NeedsCalibrationError with attributes set."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json=_NEEDS_CALIBRATION_BODY)

    client = _make_client_with_handler(handler)
    with pytest.raises(NeedsCalibrationError) as excinfo:
        client.checkout(engine="lc0", worker_id="w-1", network_name="BT4-1740")
    err = excinfo.value
    assert err.network_name == "BT4-1740"
    assert err.settings_hash == "a" * 64
    assert err.sampler_settings == _NEEDS_CALIBRATION_BODY["sampler_settings"]
    assert err.sampler_version == "v1"


def test_checkout_other_409_raises_generic_worker_client_error() -> None:
    """A 409 without NEEDS_CALIBRATION (e.g. game already claimed) is still a hard error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "Requested game is already claimed"})

    client = _make_client_with_handler(handler)
    with pytest.raises(WorkerClientError) as excinfo:
        client.checkout(engine="lc0", worker_id="w-1", game_id="g-1")
    assert not isinstance(excinfo.value, NeedsCalibrationError)


def test_checkout_forwards_network_name_when_provided() -> None:
    """When the caller supplies network_name it lands in the POST body."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"jobs": []})

    client = _make_client_with_handler(handler)
    client.checkout(engine="lc0", worker_id="w-1", network_name="BT4-1740")
    assert sent["network_name"] == "BT4-1740"
    assert sent["engine"] == "lc0"


def test_checkout_omits_network_name_when_blank() -> None:
    """The default empty network_name is not transmitted, preserving legacy shape."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"jobs": []})

    client = _make_client_with_handler(handler)
    client.checkout(engine="stockfish", worker_id="w-1")
    assert "network_name" not in sent


def test_checkout_200_exposes_draw_rate_reference_on_job() -> None:
    """The Job dataclass surfaces draw_rate_reference when the app provides it."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [{
            "id": 7,
            "game_id": "g-7",
            "pgn": "1. e4 e5",
            "engine": "lc0",
            "depth": 0,
            "nodes": 800,
            "worker_id": "w-1",
            "claimed_by_key_prefix": "abcd1234",
            "white_rating": None,
            "black_rating": None,
            "draw_rate_reference": 0.612,
        }]})

    client = _make_client_with_handler(handler)
    jobs = client.checkout(
        engine="lc0", worker_id="w-1", network_name="BT4-1740",
    )
    assert len(jobs) == 1
    assert jobs[0].draw_rate_reference == pytest.approx(0.612)
