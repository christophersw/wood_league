"""
Title: test_thresholds.py — Derivation thresholds single-source-of-truth
Description:
    Issue #161 Phase C. ``derivation.thresholds`` holds every band threshold
    and label vocabulary used by both engines' classification math. These
    tests guard the canonical values + the label set so a retune is a single,
    deliberate edit.

Changelog:
    2026-05-19 (#161/C): Initial.
"""
from __future__ import annotations

import pytest

from analysis.derivation import thresholds


def test_sf_cpl_bands_strict_ordering() -> None:
    """Stockfish CPL bands ascend: excellent < inaccuracy < mistake < blunder."""
    assert (
        thresholds.SF_EXCELLENT_CPL
        < thresholds.SF_INACCURACY_CPL
        < thresholds.SF_MISTAKE_CPL
        < thresholds.SF_BLUNDER_CPL
    )


def test_sf_top_tier_gaps_and_ceiling() -> None:
    """SF Brilliant requires a strictly bigger gap than Great and a mover ceiling."""
    assert thresholds.SF_BRILLIANT_GAP > thresholds.SF_GREAT_GAP
    assert 0.0 < thresholds.SF_BRILLIANT_WINPCT_CEILING <= 100.0


def test_lc0_delta_winpct_bands_strict_ordering() -> None:
    """Lc0 ΔWin% bands ascend: excellent < inaccuracy < mistake < blunder."""
    assert (
        thresholds.LC0_EXCELLENT_MIN
        < thresholds.LC0_INACCURACY_MIN
        < thresholds.LC0_MISTAKE_MIN
        < thresholds.LC0_BLUNDER_MIN
    )


def test_lc0_top_tier_gaps_and_ceiling() -> None:
    """Lc0 Brilliant requires a strictly bigger Win% gap than Great."""
    assert thresholds.LC0_BRILLIANT_GAP > thresholds.LC0_GREAT_GAP
    assert 0.0 < thresholds.LC0_BRILLIANT_WINPCT_CEILING <= 100.0


def test_severity_labels_canonical_set() -> None:
    """The label vocabulary is fixed and ordered from best to worst."""
    assert thresholds.SEVERITY_LABELS == (
        "Brilliant", "Great", "Best", "Excellent",
        "Inaccuracy", "Mistake", "Blunder",
    )


def test_counter_labels_subset_of_severity_labels() -> None:
    """Aggregate counters use a subset of the full severity vocabulary."""
    assert set(thresholds.COUNTER_LABELS) <= set(thresholds.SEVERITY_LABELS)
    assert thresholds.COUNTER_LABELS == ("Blunder", "Mistake", "Inaccuracy")


@pytest.mark.parametrize("attr", [
    "SF_EXCELLENT_CPL", "SF_INACCURACY_CPL", "SF_MISTAKE_CPL", "SF_BLUNDER_CPL",
    "LC0_EXCELLENT_MIN", "LC0_INACCURACY_MIN", "LC0_MISTAKE_MIN", "LC0_BLUNDER_MIN",
])
def test_canonical_values_match_analysis_math_spec(attr: str) -> None:
    """The canonical numbers below are the contract; bumping them is a retune."""
    canonical = {
        "SF_EXCELLENT_CPL": 10,
        "SF_INACCURACY_CPL": 50,
        "SF_MISTAKE_CPL": 100,
        "SF_BLUNDER_CPL": 300,
        "LC0_EXCELLENT_MIN": 1.0,
        "LC0_INACCURACY_MIN": 2.0,
        "LC0_MISTAKE_MIN": 5.0,
        "LC0_BLUNDER_MIN": 10.0,
    }
    assert getattr(thresholds, attr) == canonical[attr]
