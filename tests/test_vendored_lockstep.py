# Title: test_vendored_lockstep.py
# Description: Repo-root lockstep guard ensuring that vendored copies of
#   wdl_calibration.py and wdl_calibration_vectors.json in services/app are
#   byte-identical to the canonical sources in services/local_worker.  Fails
#   fast if either side drifts without the other being updated.
# Changelog:
#   2026-05-19 — Initial implementation for issue #159 Task D5.

import hashlib
import pathlib

ROOT = pathlib.Path(__file__).parent.parent

PAIRS = [
    (
        "services/local_worker/local_worker/analysis/wdl_calibration.py",
        "services/app/analysis/wdl_calibration.py",
    ),
    (
        "services/local_worker/local_worker/analysis/wdl_calibration_vectors.json",
        "services/app/analysis/wdl_calibration_vectors.json",
    ),
]


def _sha(p: str) -> str:
    """Return the SHA-256 hex digest of a file's raw bytes.

    Args:
        p: path string relative to repo root.
    Returns:
        Lowercase hex SHA-256 string.
    """
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def test_vendored_copies_are_byte_identical():
    """Assert that vendored app copies are byte-identical to the worker originals.

    Compares SHA-256 digests of each canonical/vendored pair.  A mismatch
    means one file was edited without updating the other — fix by re-running
    the vendor copy step (cp canonical vendored).

    Parameters: none.
    Returns: None (pytest assertion).
    Side effects: none.
    """
    for a, b in PAIRS:
        assert _sha(a) == _sha(b), f"VENDORED DRIFT: {a} != {b}"
