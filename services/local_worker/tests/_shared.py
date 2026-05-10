"""
Title: _shared.py — Shared test constants for the local_worker test suite
Description:
    Constants shared across multiple test modules.  Centralised here to avoid
    re-declaring the same string literals and inflating per-file Halstead effort.

Changelog:
    2026-05-10: Initial creation
"""
from __future__ import annotations

# Classification labels defined in analysis-math.md.
VALID_CLASSIFICATIONS = {
    "Brilliant", "Great", "Best", "Excellent", "Inaccuracy", "Mistake", "Blunder",
}
