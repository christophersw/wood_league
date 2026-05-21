"""
Title: test_stockfish_golden_vectors_wdl.py — Pinned SF WDL derivation outputs
Description:
    Golden-vector regression tests for #188 Phase C.  Two synthetic fixtures
    (quiet positional game and tactical game with a blunder) pin the complete
    derive_sf_game output including:
      - wdl_*_adj populated (WDL path) or null (fallback path)
      - wdl_mu non-null for WDL moves, null for fallback moves
      - Black-mover frame correction (W↔L swap in _adj)
      - Classifier labels (Best/Blunder/etc.) unchanged
      - Per-side accuracy numbers from WDL_mu

    Pre-Phase-A cp-only fixtures in test_sf_golden.py stay in place to
    cover the missing-WDL fallback path's CPL/classification contract.

Changelog:
    2026-05-21 (#188/C): Initial — two new WDL-bearing synthetic fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.derivation.stockfish import derive_sf_game

_GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden_vectors"


@pytest.mark.parametrize("name", ["sf_wdl_quiet", "sf_wdl_tactical"])
def test_sf_wdl_golden_vector(name: str) -> None:
    """Pinned derive_sf_game output for synthetic WDL-bearing payloads.

    Args:
        name: Fixture name prefix; reads ``{name}_input.json`` and
            compares against ``{name}_expected.json``.
    """
    with open(_GOLDEN_DIR / f"{name}_input.json") as fh:
        payload = json.load(fh)
    with open(_GOLDEN_DIR / f"{name}_expected.json") as fh:
        expected = json.load(fh)
    assert derive_sf_game(payload, game=None) == expected
