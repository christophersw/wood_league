"""
Title: test_network_calibration_model.py — NetworkCalibration model tests
Description:
    Phase A of issue #161. Each NetworkCalibration row records a one-shot
    population draw-rate measurement for a given (network_name, settings_hash)
    pair. The tuple is unique so concurrent submissions from racing workers
    are idempotent at the DB level.

Changelog:
    2026-05-19 (#161/A): Initial failing tests for NetworkCalibration model.
"""
from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from analysis.models import NetworkCalibration


@pytest.mark.django_db
def test_round_trip() -> None:
    """Required fields persist and read back identically."""
    cal = NetworkCalibration.objects.create(
        network_name="BT4-1740",
        settings_hash="a" * 64,
        draw_rate_reference=0.58,
        sample_size=4321,
        sem=0.0049,
        sampler_version="v1",
        submitted_by_worker_id="w-1",
    )
    cal.refresh_from_db()
    assert cal.network_name == "BT4-1740"
    assert cal.settings_hash == "a" * 64
    assert cal.draw_rate_reference == pytest.approx(0.58)
    assert cal.sample_size == 4321
    assert cal.sem == pytest.approx(0.0049)
    assert cal.sampler_version == "v1"
    assert cal.submitted_by_worker_id == "w-1"
    assert cal.measured_at is not None  # auto_now_add


@pytest.mark.django_db
def test_unique_together_network_and_hash() -> None:
    """Duplicate (network_name, settings_hash) inserts raise IntegrityError."""
    NetworkCalibration.objects.create(
        network_name="net",
        settings_hash="h" * 64,
        draw_rate_reference=0.5,
        sample_size=100,
        sem=0.01,
        sampler_version="v1",
        submitted_by_worker_id="w",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            NetworkCalibration.objects.create(
                network_name="net",
                settings_hash="h" * 64,
                draw_rate_reference=0.6,
                sample_size=200,
                sem=0.005,
                sampler_version="v1",
                submitted_by_worker_id="w2",
            )


@pytest.mark.django_db
def test_same_network_different_hash_coexists() -> None:
    """A new settings_hash for the same network creates a separate row."""
    NetworkCalibration.objects.create(
        network_name="net",
        settings_hash="a" * 64,
        draw_rate_reference=0.5,
        sample_size=100,
        sem=0.01,
        sampler_version="v1",
        submitted_by_worker_id="w",
    )
    NetworkCalibration.objects.create(
        network_name="net",
        settings_hash="b" * 64,
        draw_rate_reference=0.55,
        sample_size=120,
        sem=0.009,
        sampler_version="v2",
        submitted_by_worker_id="w",
    )
    assert NetworkCalibration.objects.filter(network_name="net").count() == 2
