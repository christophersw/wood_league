"""
Title: test_counters.py — Per-side severity-count aggregation
Description:
    Issue #161 Phase C. Per-side blunder/mistake/inaccuracy counts surfaced on
    game-level analysis rows. The counter is engine-agnostic: it bins
    classification labels by mover side and reports the canonical three
    counters from ``thresholds.COUNTER_LABELS``.

Changelog:
    2026-05-19 (#161/C): Initial.
"""
from __future__ import annotations

from analysis.derivation.counters import PerSideCounters, count_severities


def test_empty_input_returns_zero_counts() -> None:
    """No moves → every counter is zero for both sides."""
    counts = count_severities([])
    assert counts == PerSideCounters(
        white_blunders=0, white_mistakes=0, white_inaccuracies=0,
        black_blunders=0, black_mistakes=0, black_inaccuracies=0,
    )


def test_bins_by_side_and_label() -> None:
    """Each (ply, label) row is binned by side and contributes to the right counter."""
    moves = [
        (1, "Blunder"),    # White
        (2, "Mistake"),    # Black
        (3, "Inaccuracy"), # White
        (4, "Blunder"),    # Black
        (5, "Best"),       # White — not a counter
        (6, "Inaccuracy"), # Black
    ]
    counts = count_severities(moves)
    assert counts == PerSideCounters(
        white_blunders=1, white_mistakes=0, white_inaccuracies=1,
        black_blunders=1, black_mistakes=1, black_inaccuracies=1,
    )


def test_ignores_non_counter_labels() -> None:
    """Brilliant/Great/Best/Excellent never increment any counter."""
    moves = [(i, label) for i, label in enumerate(
        ["Brilliant", "Great", "Best", "Excellent"], start=1,
    )]
    counts = count_severities(moves)
    assert counts == PerSideCounters(
        white_blunders=0, white_mistakes=0, white_inaccuracies=0,
        black_blunders=0, black_mistakes=0, black_inaccuracies=0,
    )


def test_ignores_unknown_labels_without_raising() -> None:
    """Labels outside the spec vocabulary are silently dropped (forward-compat)."""
    counts = count_severities([(1, "Unknown"), (2, "Blunder")])
    assert counts.black_blunders == 1
    assert counts.white_blunders == 0


def test_handles_none_label() -> None:
    """A None label (e.g. terminal moves with no classification) is ignored."""
    counts = count_severities([(1, None), (2, "Mistake"), (3, "Blunder")])
    assert counts.black_mistakes == 1
    assert counts.white_blunders == 1
