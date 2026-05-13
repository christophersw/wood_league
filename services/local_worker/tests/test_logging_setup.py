"""
Title: test_logging_setup.py — Unit tests for logging_setup module
Description:
    Covers the loguru-based logging configuration, the environment
    detection helpers, and the intercept handler that bridges stdlib
    logging into loguru.

Changelog:
    2026-05-12: Initial creation. Issue #43.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from loguru import logger

from local_worker import logging_setup
from local_worker.logging_setup import (
    _detect_environment,
    _InterceptHandler,
    _normalize_level,
    configure_logging,
    log_session_banner,
)


@pytest.fixture(autouse=True)
def _isolate_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every test's log output into a temp directory."""
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    yield tmp_path
    # Tear down any sinks the test installed.
    logger.remove()


def test_configure_logging_resets_file_on_request(_isolate_log_dir: Path) -> None:
    """``reset_file=True`` should truncate any prior contents."""
    log_file = _isolate_log_dir / "worker.log"
    log_file.write_text("old content\n", encoding="utf-8")

    returned = configure_logging(level="INFO", reset_file=True)
    assert returned == log_file
    logger.info("hello world")
    logger.remove()  # flush sinks before reading

    text = log_file.read_text(encoding="utf-8")
    assert "old content" not in text
    assert "hello world" in text


def test_configure_logging_preserves_file_when_not_resetting(
    _isolate_log_dir: Path,
) -> None:
    """``reset_file=False`` must not touch the primary worker.log."""
    log_file = _isolate_log_dir / "worker.log"
    log_file.write_text("prior session\n", encoding="utf-8")

    configure_logging(level="WARNING", reset_file=False)
    logger.warning("read-only sink line")
    logger.remove()

    assert log_file.read_text(encoding="utf-8") == "prior session\n"
    diagnostics = _isolate_log_dir / "worker.diagnostics.log"
    assert diagnostics.exists()
    assert "read-only sink line" in diagnostics.read_text(encoding="utf-8")


def test_configure_logging_honours_level_threshold(_isolate_log_dir: Path) -> None:
    """Messages below the threshold must be filtered out of the file."""
    configure_logging(level="ERROR", reset_file=True)
    logger.info("ignored")
    logger.error("kept")
    logger.remove()

    text = (_isolate_log_dir / "worker.log").read_text(encoding="utf-8")
    assert "ignored" not in text
    assert "kept" in text


def test_normalize_level_falls_back_to_info() -> None:
    """Unknown level names should degrade to INFO."""
    assert _normalize_level("debug") == "DEBUG"
    assert _normalize_level("verbose-please") == "INFO"
    assert _normalize_level("") == "INFO"


def test_detect_environment_dict_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """The detector must return the documented top-level keys."""
    env = _detect_environment()
    assert set(env.keys()) >= {"host", "python", "torch", "engines"}
    assert "system" in env["host"]
    assert "version" in env["python"]
    assert "available" in env["torch"]
    assert "stockfish" in env["engines"]


def test_detect_environment_unknown_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a probe raises, the value should degrade to 'unknown'."""
    def boom() -> str:
        raise RuntimeError("no probe for you")

    monkeypatch.setattr(logging_setup.platform, "system", boom)
    env = _detect_environment()
    assert env["host"]["system"] == "unknown"


def test_intercept_handler_forwards_stdlib_records(
    _isolate_log_dir: Path,
) -> None:
    """Stdlib log records should appear in the loguru sink."""
    configure_logging(level="DEBUG", reset_file=True)
    stdlib_logger = logging.getLogger("third_party_library")
    stdlib_logger.warning("via stdlib")
    logger.remove()

    text = (_isolate_log_dir / "worker.log").read_text(encoding="utf-8")
    assert "via stdlib" in text


def test_intercept_handler_class_is_handler() -> None:
    """Sanity check the class hierarchy required by ``logging.basicConfig``."""
    assert issubclass(_InterceptHandler, logging.Handler)


def test_log_session_banner_writes_expected_prefix(
    _isolate_log_dir: Path,
) -> None:
    """Banner should emit a header line and the canonical sub-lines."""
    log_file = configure_logging(level="INFO", reset_file=True)
    log_session_banner(log_file)
    logger.remove()

    text = log_file.read_text(encoding="utf-8")
    assert "wood-league-worker" in text
    assert "host:" in text
    assert "engines:" in text
