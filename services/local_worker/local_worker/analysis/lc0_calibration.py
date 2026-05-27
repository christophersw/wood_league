"""
Title: lc0_calibration.py — Per-network draw-rate constant
Description:
    Single source of truth for the draw_rate_reference fed into the lc0
    WDL/contempt calibration. Pairs with the network shipped in
    ``commands/_downloads.py`` (BT4-1024x15x32h-swa-6147500-policytune-332).

    Replaces the prior NetworkCalibration sampler pipeline (issue #161 Phase A/B,
    removed in #214). To retune or swap networks, update both this constant
    and the BT4 URL/filename together.

Changelog:
    2026-05-27 (#214): Initial — pin to 0.62 for BT4-it332.
"""
from __future__ import annotations

import logging

# Measured against BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz.
LC0_DRAW_RATE_REFERENCE: float = 0.62

# Fingerprint substring the resolved network name must contain for the
# pinned constant to be meaningful. Kept lowercase for case-insensitive
# substring match against either an Lc0 id-name token (e.g. "BT4") or a
# weights filename stem (e.g. "BT4-1024x15x32h-swa-...-policytune-332").
LC0_DRAW_RATE_NETWORK_FINGERPRINT: str = "bt4"

_log = logging.getLogger(__name__)


def warn_if_network_mismatches_calibration(network_name: str) -> bool:
    """Log a loud warning when the resolved lc0 network is not the BT4 family
    the ``LC0_DRAW_RATE_REFERENCE`` constant was measured against.

    The constant is a per-network property of the BT4 policytune-332 weights;
    running the worker with different weights (e.g. a future upgrade, a test
    net, an accidental rollback) silently produces wrong WDL calibration. This
    helper surfaces that drift in the worker log without aborting startup, so
    operators see it the first time a fresh engine is launched.

    Args:
        network_name: Resolved network identifier from ``_parse_network_name``
            (engine id-name parenthetical or weights filename stem).

    Returns:
        ``True`` when the network looks like the calibrated family (no warning
        emitted); ``False`` when a mismatch was detected and logged. Returned
        so callers and tests can assert on the outcome without re-parsing the
        log stream.
    """
    if LC0_DRAW_RATE_NETWORK_FINGERPRINT in network_name.lower():
        return True
    _log.warning(
        "lc0 draw_rate calibration mismatch: LC0_DRAW_RATE_REFERENCE=%.2f was "
        "measured against the BT4 network family, but the resolved network is "
        "%r. WDL calibration for every game analysed by this worker will be "
        "biased until the constant is retuned for this network (see "
        "lc0_calibration.py).",
        LC0_DRAW_RATE_REFERENCE,
        network_name or "(unknown)",
    )
    return False


__all__ = [
    "LC0_DRAW_RATE_REFERENCE",
    "LC0_DRAW_RATE_NETWORK_FINGERPRINT",
    "warn_if_network_mismatches_calibration",
]
