"""
Title: test_runpod_dispatch.py — submit_job_to_runpod payload + return-id tests
Description: Mocks runpod.Endpoint.run to verify payload shape per engine and
    that the returned RunPod job id is propagated correctly.
Changelog:
    2026-05-10: Initial — Task A4 of scrap-dispatchers plan.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from analysis.models import AnalysisJob
from analysis.services.runpod_dispatch import submit_job_to_runpod
from games.models import Game


def _make_game(pgn: str = "1. e4 *") -> Game:
    """Create a unique Game instance for testing.

    Args:
        pgn: PGN string for the game. Defaults to "1. e4 *".

    Returns:
        Game: A saved Game instance with a unique ID.
    """
    return Game.objects.create(
        id=f"test-A4-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn=pgn,
    )


@pytest.mark.django_db
def test_stockfish_payload_and_id():
    """Stockfish jobs produce the correct payload shape and propagate the RunPod job id.

    Verifies that the endpoint id comes from settings, that thread/hash settings
    are forwarded, and that the returned run_request.job_id is returned to the caller.
    """
    with override_settings(
        RUNPOD_STOCKFISH_ENDPOINT_ID="sf-ep-1",
        ANALYSIS_THREADS=8,
        ANALYSIS_HASH_MB=2048,
    ):
        game = _make_game("1. e4 *")
        job = AnalysisJob.objects.create(
            game=game, engine="stockfish", depth=20, status=AnalysisJob.STATUS_PENDING
        )

        fake_endpoint = MagicMock()
        fake_endpoint.run.return_value = MagicMock(job_id="rp-123")

        with patch(
            "analysis.services.runpod_dispatch.runpod.Endpoint",
            return_value=fake_endpoint,
        ) as ep_cls:
            result = submit_job_to_runpod(job)

        ep_cls.assert_called_once_with("sf-ep-1")
        payload = fake_endpoint.run.call_args[0][0]
        assert payload["job_id"] == job.id
        assert payload["pgn"] == "1. e4 *"
        assert payload["depth"] == 20
        assert payload["threads"] == 8
        assert payload["hash_mb"] == 2048
        assert result == "rp-123"


@pytest.mark.django_db
def test_lc0_payload_no_network():
    """Lc0 jobs with no network produce a payload without weights_path.

    Verifies that nodes defaults to the job's nodes field, and that
    weights_path is absent when LC0_NETWORK is empty.
    """
    with override_settings(
        RUNPOD_LC0_ENDPOINT_ID="lc0-ep-1",
        LC0_NODES=25000,
        LC0_NETWORK="",
    ):
        game = _make_game()
        job = AnalysisJob.objects.create(
            game=game,
            engine="lc0",
            depth=25000,
            nodes=25000,
            status=AnalysisJob.STATUS_PENDING,
        )

        fake_endpoint = MagicMock()
        fake_endpoint.run.return_value = MagicMock(job_id="rp-lc0-1")

        with patch("analysis.services.runpod_dispatch.runpod.Endpoint",
                   return_value=fake_endpoint):
            result = submit_job_to_runpod(job)

        payload = fake_endpoint.run.call_args[0][0]
        assert payload["nodes"] == 25000
        assert "weights_path" not in payload
        assert result == "rp-lc0-1"


@pytest.mark.django_db
def test_lc0_payload_with_network():
    """Lc0 jobs with a configured network include weights_path in the payload.

    Args: None — settings override provides the network path.
    """
    with override_settings(
        RUNPOD_LC0_ENDPOINT_ID="lc0-ep-2",
        LC0_NODES=10000,
        LC0_NETWORK="/models/t2-768x15.pb.gz",
    ):
        game = _make_game()
        job = AnalysisJob.objects.create(
            game=game,
            engine="lc0",
            depth=10000,
            nodes=None,  # should fall back to LC0_NODES setting
            status=AnalysisJob.STATUS_PENDING,
        )

        fake_endpoint = MagicMock()
        fake_endpoint.run.return_value = MagicMock(job_id="rp-lc0-2")

        with patch("analysis.services.runpod_dispatch.runpod.Endpoint",
                   return_value=fake_endpoint):
            submit_job_to_runpod(job)

        payload = fake_endpoint.run.call_args[0][0]
        assert payload["nodes"] == 10000  # LC0_NODES setting fallback
        assert payload["weights_path"] == "/models/t2-768x15.pb.gz"


@pytest.mark.django_db
def test_missing_endpoint_id_raises():
    """RuntimeError is raised when the engine's endpoint id is not configured.

    Verifies the guard in _endpoint_id() fires before any RunPod call is made.
    """
    with override_settings(RUNPOD_STOCKFISH_ENDPOINT_ID=""):
        game = _make_game()
        job = AnalysisJob.objects.create(
            game=game, engine="stockfish", depth=20, status=AnalysisJob.STATUS_PENDING
        )
        with pytest.raises(RuntimeError, match="not configured"):
            submit_job_to_runpod(job)


@pytest.mark.django_db
def test_unknown_engine_raises():
    """ValueError is raised for an unknown engine name.

    Verifies that _endpoint_id() rejects unsupported engine strings.
    """
    with override_settings(RUNPOD_STOCKFISH_ENDPOINT_ID="ep-1"):
        game = _make_game()
        job = AnalysisJob.objects.create(
            game=game, engine="leela", depth=20, status=AnalysisJob.STATUS_PENDING
        )
        with pytest.raises(ValueError, match="Unknown engine"):
            submit_job_to_runpod(job)
