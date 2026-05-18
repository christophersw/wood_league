"""
Title: test_tailwind_build.py — Compiled Tailwind CSS freshness guard
Description:
    The Django app serves a *committed* compiled stylesheet,
    static/css/tailwind.css, which base.html links directly. The
    authoring source is static/css/main.css (Tailwind v4,
    `@import "tailwindcss";`). Nothing in the Railway deploy or any
    build step recompiles tailwind.css, so when main.css gains new
    component classes but tailwind.css is not rebuilt, those classes
    are silently absent from the served stylesheet and the affected
    UI renders unstyled (issue #140 — the worker dashboard cards and
    "last ten games" table rendered as raw unstyled text).

    This is a pure-filesystem tripwire (no Django, no DB): every
    critical, hand-authored component selector present in main.css
    MUST also be present in the compiled tailwind.css. It fails fast
    in the normal pytest suite — and therefore in the per-edit
    quality gate and CI — even on machines without Node, so a stale
    compiled artifact can never be shipped unnoticed again.

Changelog:
    2026-05-17 (#140): Initial creation. Fails against the stale
                2026-05-07 tailwind.css that was missing every
                .dash-worker-* / card / badge class; passes once
                tailwind.css is rebuilt from main.css.
"""

from __future__ import annotations

import unittest
from pathlib import Path

_CSS_DIR = Path(__file__).resolve().parent.parent / "static" / "css"
_SOURCE = _CSS_DIR / "main.css"
_COMPILED = _CSS_DIR / "tailwind.css"

# Hand-authored component selectors that drive the dashboard and
# data tables. These are plain CSS rules in main.css (not utilities
# scanned from templates), so Tailwind passes them through verbatim
# — their absence from the compiled file means it is stale.
_CRITICAL_SELECTORS = (
    "dash-worker-grid",
    "dash-worker-card",
    "dash-worker-card__head",
    "dash-badge-live",
    "dash-recent-list",
    "dash-progress__bar",
    "dash-dot",
    "wc-table",
)


class TailwindBuildFreshnessTests(unittest.TestCase):
    """Guard: compiled tailwind.css must not lag behind main.css."""

    def test_source_and_compiled_exist(self):
        """Both the Tailwind source and compiled artifact are present.

        Returns:
            None: assertion failure if either file is missing.
        """
        self.assertTrue(_SOURCE.is_file(), f"missing {_SOURCE}")
        self.assertTrue(_COMPILED.is_file(), f"missing {_COMPILED}")

    def test_critical_selectors_compiled(self):
        """Every critical selector in main.css is in tailwind.css.

        For each entry in _CRITICAL_SELECTORS that the authoring
        source defines, the compiled stylesheet that base.html
        actually serves must contain it too. A miss means
        tailwind.css was not rebuilt after main.css changed.

        Returns:
            None: assertion failure listing every selector that is
            present in main.css but absent from the compiled output.
        """
        source = _SOURCE.read_text(encoding="utf-8")
        compiled = _COMPILED.read_text(encoding="utf-8")

        stale = [
            selector
            for selector in _CRITICAL_SELECTORS
            if selector in source and selector not in compiled
        ]

        self.assertEqual(
            stale,
            [],
            "static/css/tailwind.css is STALE — these selectors exist "
            f"in main.css but not in the compiled file: {stale}. "
            "Rebuild with services/app/bin/build_tailwind.sh.",
        )


if __name__ == "__main__":
    unittest.main()
