from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Areas loaded by Streamlit navigation where we previously hit runtime errors.
CHECK_GLOBS = [
    "app/web/pages/*.py",
    "app/web/components/*.py",
]

# Modules where PEP 604 in SQLAlchemy mapped annotations caused runtime failures.
NO_PEP604_FILES = [
    "app/storage/models.py",
]


def _has_future_annotations(text: str) -> bool:
    return bool(
        re.search(
            r"^\s*from\s+__future__\s+import\s+annotations\s*$",
            text,
            flags=re.MULTILINE,
        )
    )


def _contains_pep604_union(text: str) -> bool:
    # Broad signal for inline unions in annotations, e.g. int | None, A | B.
    return bool(
        re.search(
            r"\b[A-Za-z_][A-Za-z0-9_\.\[\]]*\s*\|\s*[A-Za-z_][A-Za-z0-9_\.\[\]]*", text
        )
    )


class TestPython39AnnotationCompatibility(unittest.TestCase):
    def test_modules_with_pep604_union_have_future_annotations(self) -> None:
        files: list[Path] = []
        for glob in CHECK_GLOBS:
            files.extend(ROOT.glob(glob))

        self.assertTrue(files, "No files found for annotation compatibility checks")

        failures: list[str] = []
        for path in sorted(files):
            text = path.read_text(encoding="utf-8")
            if _contains_pep604_union(text) and not _has_future_annotations(text):
                failures.append(str(path.relative_to(ROOT)))

        self.assertEqual(
            failures,
            [],
            (
                "Files using PEP 604 unions must include "
                "`from __future__ import annotations` for Python 3.9 compatibility: "
                f"{failures}"
            ),
        )

    def test_sqlalchemy_models_do_not_use_pipe_unions(self) -> None:
        failures: list[str] = []

        for rel in NO_PEP604_FILES:
            path = ROOT / rel
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
