"""
Title: test_claim_jobs_calibration.py — Phase B checkout pre-flight tests
Description:
    Issue #161 Phase B. ``claim_jobs`` is the single choke point that decides
    whether an lc0 worker is allowed to receive jobs against a given network.
    These tests cover:

    * Missing calibration row → ``NeedsCalibration`` raised with metadata.
    * Present calibration row → jobs returned, draw_rate_reference attached.
    * Empty ``network_name`` (stockfish, or legacy lc0 caller) → no pre-flight.

Changelog:
    2026-05-19 (#161/B): Initial.
"""
from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from analysis.calibration_hash import current_lc0_settings_hash
from analysis.models import AnalysisJob, NetworkCalibration
from analysis.services import jobs as job_service
from games.models import Game


def _make_lc0_job() -> AnalysisJob:
    """Create a pending lc0 AnalysisJob against a fresh Game."""
    game = Game.objects.create(
        id=f"phaseB-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )
    return AnalysisJob.objects.create(
        game=game, engine="lc0", status=AnalysisJob.STATUS_PENDING,
    )


@pytest.mark.django_db
def test_lc0_checkout_without_calibration_raises_needs_calibration():
    """An uncalibrated network triggers NeedsCalibration with sampler metadata."""
    _make_lc0_job()
    with pytest.raises(job_service.NeedsCalibration) as excinfo:
        job_service.claim_jobs(
            engine="lc0", batch_size=1, worker_id="w-1", network_name="UncalibNet",
        )
    err = excinfo.value
    assert err.network_name == "UncalibNet"
    assert err.settings_hash == current_lc0_settings_hash()
    assert err.sampler_settings["sampler_version"] == err.sampler_version
    assert set(err.sampler_settings) == {
        "sem_target", "nodes", "max_positions", "sampler_version",
    }
    # No job was claimed — still pending.
    assert AnalysisJob.objects.filter(status=AnalysisJob.STATUS_PENDING).count() == 1


@pytest.mark.django_db
def test_lc0_checkout_with_calibration_attaches_draw_rate_reference():
    """A calibrated network claims the job and annotates draw_rate_reference."""
    _make_lc0_job()
    NetworkCalibration.objects.create(
        network_name="CalibNet",
        settings_hash=current_lc0_settings_hash(),
        draw_rate_reference=0.612,
        sample_size=4321,
        sem=0.0049,
        sampler_version="v1",
        submitted_by_worker_id="w-other",
    )
    claimed = job_service.claim_jobs(
        engine="lc0", batch_size=1, worker_id="w-1", network_name="CalibNet",
    )
    assert len(claimed) == 1
    assert claimed[0].draw_rate_reference == pytest.approx(0.612)
    assert claimed[0].status == AnalysisJob.STATUS_RUNNING


@pytest.mark.django_db
def test_lc0_checkout_without_network_name_skips_preflight():
    """An lc0 checkout that omits network_name bypasses calibration (legacy)."""
    _make_lc0_job()
    claimed = job_service.claim_jobs(
        engine="lc0", batch_size=1, worker_id="w-1",
    )
    assert len(claimed) == 1
    assert getattr(claimed[0], "draw_rate_reference", None) is None


@pytest.mark.django_db
def test_stockfish_checkout_ignores_network_name():
    """A stockfish checkout never pre-flights calibration, even with a network_name."""
    game = Game.objects.create(
        id=f"phaseB-sf-{uuid.uuid4().hex[:8]}",
        played_at=timezone.now(),
        time_control="600",
        pgn="1. e4 e5 *",
    )
    AnalysisJob.objects.create(
        game=game, engine="stockfish", status=AnalysisJob.STATUS_PENDING,
    )
    claimed = job_service.claim_jobs(
        engine="stockfish", batch_size=1, worker_id="w-1",
        network_name="WouldBe409ForLc0",
    )
    assert len(claimed) == 1
