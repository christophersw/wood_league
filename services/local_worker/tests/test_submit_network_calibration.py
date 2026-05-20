"""
Title: test_submit_network_calibration.py — WorkerClient.submit_network_calibration
Description:
    Phase A of issue #161. Smoke-test the HTTP shape of the worker-side
    calibration submitter: POST body lines up with the app's
    NetworkCalibrationSubmitSerializer, 200 idempotent no-op surfaces
    cleanly, 4xx surfaces as WorkerClientError. Uses httpx.MockTransport
    via direct monkeypatch — no network IO.

Changelog:
    2026-05-19 (#161/A): Initial.
"""
from __future__ import annotations

import json

import httpx
import pytest

from local_worker.worker_client import WorkerClient, WorkerClientError


def _install_transport(client: WorkerClient, handler) -> None:
    """Swap the client's httpx transport for a MockTransport calling ``handler``.

    Args:
        client: WorkerClient whose internal httpx.Client to replace.
        handler: Callable taking ``httpx.Request`` and returning ``httpx.Response``.
    """
    client._http = httpx.Client(  # noqa: SLF001 - test-only injection
        headers={"X-Api-Key": "k", "Content-Type": "application/json"},
        transport=httpx.MockTransport(handler),
        timeout=5,
    )


def _make_client() -> WorkerClient:
    """Construct a WorkerClient pointed at a stub base URL."""
    return WorkerClient(base_url="https://app.test", api_key="k")


def test_submit_network_calibration_posts_expected_body() -> None:
    """The POST body matches NetworkCalibrationSubmitSerializer's contract."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"created": True})

    client = _make_client()
    _install_transport(client, handler)
    result = client.submit_network_calibration(
        network_name="BT4-1740",
        settings_hash="a" * 64,
        draw_rate_reference=0.58,
        sample_size=4321,
        sem=0.0049,
        sampler_version="v1",
        worker_id="w-1",
    )
    assert result == {"created": True}
    assert captured["url"] == "https://app.test/api/v1/network_calibrations/"
    assert captured["body"] == {
        "network_name": "BT4-1740",
        "settings_hash": "a" * 64,
        "draw_rate_reference": 0.58,
        "sample_size": 4321,
        "sem": 0.0049,
        "sampler_version": "v1",
        "worker_id": "w-1",
    }


def test_submit_network_calibration_200_is_idempotent_no_op() -> None:
    """Response with ``created=False`` (200) is returned verbatim, no error."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": False, "sample_size": 100})

    client = _make_client()
    _install_transport(client, handler)
    body = client.submit_network_calibration(
        network_name="n",
        settings_hash="b" * 64,
        draw_rate_reference=0.5,
        sample_size=100,
        sem=0.01,
        sampler_version="v1",
        worker_id="w",
    )
    assert body["created"] is False
    assert body["sample_size"] == 100


def test_submit_network_calibration_raises_on_4xx() -> None:
    """A 400 from the app surfaces as WorkerClientError without retry."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"draw_rate_reference": ["invalid"]})

    client = _make_client()
    _install_transport(client, handler)
    with pytest.raises(WorkerClientError):
        client.submit_network_calibration(
            network_name="n",
            settings_hash="c" * 64,
            draw_rate_reference=1.5,
            sample_size=1,
            sem=0.0,
            sampler_version="v1",
            worker_id="w",
        )
