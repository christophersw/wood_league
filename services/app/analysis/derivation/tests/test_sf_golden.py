"""
Title: test_sf_golden.py — Frozen Stockfish classification + CPL contract
Description:
    Issue #161 Phase E. ``derivation/golden_vectors/stockfish.json`` pins the
    expected outputs of ``classify_sf_move`` and ``cpl`` for a representative
    cross-section of CPL / gap / Win% / SEE inputs. Any drift in the band
    ladder, the threshold values in ``derivation.thresholds``, or the
    frame-flip helper fails this test loudly.

Changelog:
    2026-05-19 (#161/E): Initial.
"""
from __future__ import annotations

import json
import pathlib

from analysis.derivation.stockfish import classify_sf_move, cpl

_FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "golden_vectors" / "stockfish.json"
)


def test_cpl_cases_match_golden_vectors() -> None:
    """Every cpl fixture row matches the ported math byte-for-byte."""
    data = json.loads(_FIXTURE.read_text())
    rows = [c for c in data["cases"] if c["kind"] == "cpl"]
    assert rows, "fixture must contain cpl cases"
    for case in rows:
        assert cpl(**case["in"]) == case["out"], case["name"]


def test_classify_cases_match_golden_vectors() -> None:
    """Every classify fixture row maps to the same severity label."""
    data = json.loads(_FIXTURE.read_text())
    rows = [c for c in data["cases"] if c["kind"] == "classify"]
    assert rows, "fixture must contain classify cases"
    for case in rows:
        assert classify_sf_move(**case["in"]) == case["out"], case["name"]


def test_thresholds_reference_recorded() -> None:
    """The fixture records the thresholds module it was generated against."""
    data = json.loads(_FIXTURE.read_text())
    assert data.get("_thresholds_ref") == "derivation.thresholds"
    assert isinstance(data.get("_band_ladder_version"), int)
