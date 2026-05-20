"""
Title: derivation — App-owned calibration + classification math
Description:
    Issue #161. Engine workers emit raw observables; the Django app derives
    every calibrated, classified, or aggregated field at submission time.
    This package is the single home for that derivation:

      * ``thresholds``  — band thresholds + label vocabulary
      * ``accuracy``    — Lichess Win% / move-accuracy / game-accuracy
      * ``counters``    — per-side severity counts
      * ``_frame``      — mover↔white frame conversion
      * ``lc0``         — Lc0 orchestrator (Phase D)
      * ``stockfish``   — Stockfish orchestrator (Phase E)

    Phase C scope (this commit): package skeleton + the four shared utilities.
    Phase D / E plug the math + golden-vector contracts.

Changelog:
    2026-05-19 (#161/C): Initial skeleton.
"""
from analysis.derivation.lc0 import derive_lc0_game
from analysis.derivation.stockfish import derive_sf_game

__all__ = ["derive_lc0_game", "derive_sf_game"]
