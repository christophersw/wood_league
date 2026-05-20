"""
Title: counters.py — Per-side severity counters for game-level analysis rows
Description:
    Issue #161 Phase C. Bins classification labels by mover side (deduced from
    ply parity) and emits the canonical three counters
    (Blunder/Mistake/Inaccuracy) for both colours. Engine-agnostic: the input
    is a list of ``(ply, label)`` tuples; the output is the
    ``Game.*_blunders / *_mistakes / *_inaccuracies`` payload.

Changelog:
    2026-05-19 (#161/C): Initial.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from analysis.derivation._frame import is_white_ply
from analysis.derivation.thresholds import COUNTER_LABELS


@dataclass(frozen=True)
class PerSideCounters:
    """Frozen tuple of per-side severity counts ready for the analysis row."""

    white_blunders: int
    white_mistakes: int
    white_inaccuracies: int
    black_blunders: int
    black_mistakes: int
    black_inaccuracies: int


def count_severities(
    classified_moves: Iterable[tuple[int, Optional[str]]],
) -> PerSideCounters:
    """Bin classification labels by mover side and return the per-side counters.

    Labels outside ``thresholds.COUNTER_LABELS`` (Brilliant/Great/Best/Excellent,
    None for terminal moves, or anything unknown) are silently ignored so that
    bumping the band vocabulary in ``thresholds`` does not cascade-fail older
    callers.

    Args:
        classified_moves: Iterable of ``(ply, label)`` tuples. ``ply`` is the
            1-based ply index; ``label`` is the severity string emitted by
            the engine-specific classifier (or None).

    Returns:
        A ``PerSideCounters`` with the six fields populated.
    """
    buckets = {
        (chess_white, label): 0
        for chess_white in (True, False)
        for label in COUNTER_LABELS
    }
    for ply, label in classified_moves:
        if label not in COUNTER_LABELS:
            continue
        buckets[(is_white_ply(ply), label)] += 1
    return PerSideCounters(
        white_blunders=buckets[(True, "Blunder")],
        white_mistakes=buckets[(True, "Mistake")],
        white_inaccuracies=buckets[(True, "Inaccuracy")],
        black_blunders=buckets[(False, "Blunder")],
        black_mistakes=buckets[(False, "Mistake")],
        black_inaccuracies=buckets[(False, "Inaccuracy")],
    )
