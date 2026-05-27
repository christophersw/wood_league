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

# Measured against BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz.
LC0_DRAW_RATE_REFERENCE: float = 0.62

__all__ = ["LC0_DRAW_RATE_REFERENCE"]
