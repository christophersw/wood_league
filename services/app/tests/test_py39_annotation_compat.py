"""
Title: test_py39_annotation_compat.py — Python annotation compatibility checks
Description:
    Validates annotation usage across the Django codebase.

    Originally written when the project targeted Python 3.9 (Streamlit layout)
    and required `from __future__ import annotations` to use PEP 604 `X | Y`
    union syntax.  The project now runs Python 3.13 and uses a Django layout,
    so the `from __future__ import annotations` guard is no longer required —
    PEP 604 unions are supported natively.

    The remaining check ensures that SQLAlchemy mapped-column annotations avoid
    bare `|` pipe unions, because SQLAlchemy's mapper introspects annotations
    at *runtime* (not import time) and cannot handle the new-style syntax in
    mapped columns even on 3.13.

Changelog:
    2026-05-08: Removed Streamlit glob check (paths no longer exist after
                Django migration); relaxed future-annotations requirement now
                that the runtime is Python 3.13.  Retained SQLAlchemy model
                check which is still relevant.
    2025-xx-xx: Initial version for Python 3.9 / Streamlit project.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Modules where PEP 604 in SQLAlchemy mapped annotations caused runtime
# failures even on Python 3.13 (mapper evaluates annotations at runtime).
NO_PEP604_FILES = [
    "app/storage/models.py",
]


def _has_future_annotations(text: str) -> bool:
    """Return True if *text* contains a ``from __future__ import annotations`` line.

    Parameters:
        text: Full source text of a Python module.

    Returns:
        bool: True when the future import is present, False otherwise.
    """
    return bool(
        re.search(
            r"^\s*from\s+__future__\s+import\s+annotations\s*$",
            text,
            flags=re.MULTILINE,
        )
    )


def _contains_pep604_union(text: str) -> bool:
    """Return True if *text* contains an inline PEP 604 ``X | Y`` union.

    Matches broad annotation-style unions such as ``int | None`` or
    ``list[str] | None``.  May produce false positives for bitwise-OR
    expressions, but is conservative enough for this lint purpose.

    Parameters:
        text: Full source text of a Python module.

    Returns:
        bool: True when at least one pipe-union pattern is found.
    """
    return bool(
        re.search(
            r"\b[A-Za-z_][A-Za-z0-9_\.\[\]]*\s*\|\s*[A-Za-z_][A-Za-z0-9_\.\[\]]*",
            text,
        )
    )


class TestPython313AnnotationCompatibility(unittest.TestCase):
    """Annotation compatibility checks for the Python 3.13 / Django codebase."""

    def test_runtime_is_python_313_or_later(self) -> None:
        """Assert the test suite is running on Python 3.13+.

        This documents the project's minimum runtime requirement and will
        surface immediately if the environment is misconfigured.

        Returns:
            None — asserts via unittest.
        """
        self.assertGreaterEqual(
            sys.version_info,
            (3, 13),
            f"Project requires Python 3.13+; running {sys.version}",
        )

    def test_sqlalchemy_models_do_not_use_pipe_unions(self) -> None:
        """Assert that SQLAlchemy mapped-column files avoid bare ``|`` unions.

        SQLAlchemy's declarative mapper evaluates ``Mapped[X]`` annotations
        at runtime regardless of Python version.  Using ``int | None`` inside
        a ``Mapped`` type therefore raises ``TypeError`` at startup even on
        Python 3.13.  Files in ``NO_PEP604_FILES`` must use
        ``Optional``/``Union`` instead.

        Returns:
            None — asserts via unittest.
        """
        failures: list[str] = []

        for rel in NO_PEP604_FILES:
            path = ROOT / rel
            if not path.exists():
                # File removed or renamed — skip rather than hard-fail so the
                # test list can be updated separately.
                continue
            text = path.read_text(encoding="utf-8")
            if _contains_pep604_union(text):
                failures.append(rel)

        self.assertEqual(
            failures,
            [],
            (
                "SQLAlchemy model annotations must avoid `|` unions "
                "(use Optional/Union) to prevent mapped annotation resolution errors: "
                f"{failures}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
