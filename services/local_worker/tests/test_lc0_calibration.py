"""
Title: test_lc0_calibration.py — Tests for the pinned draw-rate constant and guard
Description:
    Covers the worker-side LC0_DRAW_RATE_REFERENCE constant (#214) and the
    network-fingerprint guard that warns when the constant is being applied
    to a network other than the BT4 family it was measured against.

Changelog:
    2026-05-27 (#214): Initial — guard regression tests + constant value pin.
"""
from __future__ import annotations

import logging

import pytest

from local_worker.analysis.lc0_calibration import (
    LC0_DRAW_RATE_NETWORK_FINGERPRINT,
    LC0_DRAW_RATE_REFERENCE,
    warn_if_network_mismatches_calibration,
)


def test_constant_pinned_to_bt4_value() -> None:
    """Lock the pinned reference; bumping it requires re-measuring."""
    assert LC0_DRAW_RATE_REFERENCE == pytest.approx(0.62)
    assert LC0_DRAW_RATE_NETWORK_FINGERPRINT == "bt4"


@pytest.mark.parametrize(
    "network_name",
    [
        "BT4",
        "BT4-1024x15x32h-swa-6147500-policytune-332",
        "Lc0 v0.30 (BT4)",
        "bt4-it332",
    ],
)
def test_bt4_family_passes_guard_silently(
    network_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Resolved network names containing the BT4 fingerprint must not warn."""
    caplog.set_level(logging.WARNING, logger="local_worker.analysis.lc0_calibration")
    assert warn_if_network_mismatches_calibration(network_name) is True
    assert caplog.records == []


@pytest.mark.parametrize(
    "network_name",
    [
        "",
        "T78",
        "Lc0 v0.30 (T82-7464000)",
        "some-other-net.pb.gz",
    ],
)
def test_non_bt4_network_logs_calibration_mismatch(
    network_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Non-BT4 networks must emit a single WARNING naming the resolved network."""
    caplog.set_level(logging.WARNING, logger="local_worker.analysis.lc0_calibration")
    assert warn_if_network_mismatches_calibration(network_name) is False
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "calibration mismatch" in record.getMessage()
    expected = network_name or "(unknown)"
    assert expected in record.getMessage()
