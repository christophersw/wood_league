"""
Title: thresholds.py — Engine-agnostic classification thresholds + label vocab
Description:
    Issue #161 Phase C. Single source of truth for every band threshold and
    label used by ``derivation.lc0`` and ``derivation.stockfish``. Tuning a
    band — say raising the SF blunder cutoff or moving the lc0 inaccuracy
    boundary — is a one-file edit here; the math modules read these constants
    and apply them at submission time, never on the worker.

    Values mirror ``analysis-math.md`` (the project's classification spec) and
    are unchanged from the existing worker math (pre-#161); the move here is
    purely architectural.

Changelog:
    2026-05-19 (#161/C): Initial — ported from local_worker.analysis.math.
"""
from __future__ import annotations

# ── Stockfish (CPL-based) bands ──────────────────────────────────────────
# A move's classification is the first band its CPL falls into.
SF_EXCELLENT_CPL = 10     # cpl < 10  → top-tier resolver runs
SF_INACCURACY_CPL = 50    # cpl < 50  → Excellent
SF_MISTAKE_CPL = 100      # cpl < 100 → Inaccuracy
SF_BLUNDER_CPL = 300      # cpl < 300 → Mistake; cpl ≥ 300 → Blunder

# Top-tier resolver gaps (Brilliant > Great > Best) when cpl < SF_EXCELLENT_CPL.
SF_BRILLIANT_GAP = 150          # cp gap between #1 and #2 for Brilliant
SF_GREAT_GAP = 80               # cp gap for Great
SF_BRILLIANT_WINPCT_CEILING = 70.0  # mover Win% must be below this for Brilliant

# ── Lc0 (ΔWin%-based) bands ──────────────────────────────────────────────
# A move's classification is the first band its ΔWin% (mover-frame Win% drop)
# falls into. ``EXCELLENT_MIN`` is the *exclusive* upper bound of the top tier.
LC0_EXCELLENT_MIN = 1.0    # Δ ≤ 1.0 → top-tier resolver runs
LC0_INACCURACY_MIN = 2.0   # Δ < 2.0 → Excellent
LC0_MISTAKE_MIN = 5.0      # Δ < 5.0 → Inaccuracy
LC0_BLUNDER_MIN = 10.0     # Δ < 10.0 → Mistake; Δ ≥ 10.0 → Blunder

LC0_BRILLIANT_GAP = 10.0   # Win% gap between #1 and #2 for Brilliant
LC0_GREAT_GAP = 6.0        # Win% gap for Great
LC0_BRILLIANT_WINPCT_CEILING = 70.0

# ── Label vocabulary ─────────────────────────────────────────────────────
# Best-to-worst order. Code that iterates expects this exact tuple.
SEVERITY_LABELS: tuple[str, ...] = (
    "Brilliant", "Great", "Best", "Excellent",
    "Inaccuracy", "Mistake", "Blunder",
)

# Subset surfaced as per-side counters on game-level analysis rows.
COUNTER_LABELS: tuple[str, ...] = ("Blunder", "Mistake", "Inaccuracy")
