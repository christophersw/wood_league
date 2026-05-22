"""
Title: test_win_pct_caller_audit.py — Pin the sole accuracy.win_pct caller (#197)
Description:
    #197 retired the legacy mover-frame sigmoid Win% scalars (arrow_score_*).
    After that removal the cp-sigmoid ``accuracy.win_pct`` must survive only as
    the documented missing-WDL accuracy fallback inside
    ``derivation.stockfish``. This AST audit fails loud if any new caller
    reintroduces a sigmoid Win% path (e.g. a resurrected arrow_score gap or a
    win_pct call leaking into the LC0 derivation, the classifier, or the
    candidate-gap math).

Changelog:
    2026-05-22 (#197): Initial — guards the post-retirement win_pct contract.
"""
from __future__ import annotations

import ast
from pathlib import Path

_DERIVATION_DIR = Path(__file__).resolve().parent.parent

# win_pct is the cp→Win% sigmoid. After #197 its only legitimate uses are the
# missing-WDL accuracy fallback in _derive_one_move and the initial-position
# seed for the White-frame accuracy walk.
_ALLOWED_CALLERS = {"_derive_one_move", "_initial_win_pct_white"}


def _win_pct_callers(source: str) -> dict[str, set[str]]:
    """Map each enclosing function/method to the win_pct calls it makes.

    Args:
        source: Python source text of a derivation module.

    Returns:
        Dict of ``function_name -> {"win_pct"}`` for every function that calls
        ``win_pct(...)``. Module-level calls are keyed under ``"<module>"``.
    """
    tree = ast.parse(source)
    callers: dict[str, set[str]] = {}

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.scope = "<module>"

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            prev = self.scope
            self.scope = node.name
            self.generic_visit(node)
            self.scope = prev

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "win_pct":
                callers.setdefault(self.scope, set()).add("win_pct")
            self.generic_visit(node)

    _Visitor().visit(tree)
    return callers


def test_win_pct_only_called_from_stockfish_fallback() -> None:
    """win_pct lives only in the stockfish missing-WDL fallback path (#197)."""
    callers = _win_pct_callers((_DERIVATION_DIR / "stockfish.py").read_text())
    assert set(callers) <= _ALLOWED_CALLERS, (
        f"Unexpected win_pct caller(s) in stockfish.py: "
        f"{set(callers) - _ALLOWED_CALLERS}. The cp sigmoid must stay confined "
        f"to the documented missing-WDL fallback (#197)."
    )


def test_win_pct_not_used_in_lc0_derivation() -> None:
    """The LC0 derivation is WDL-native and must never call the cp sigmoid."""
    callers = _win_pct_callers((_DERIVATION_DIR / "lc0.py").read_text())
    assert not callers, (
        f"win_pct (cp sigmoid) leaked into lc0.py: {set(callers)}. LC0 accuracy "
        f"is WDL-native and must not use the Stockfish fallback sigmoid."
    )
