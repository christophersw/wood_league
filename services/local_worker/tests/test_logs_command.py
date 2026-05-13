"""
Title: test_logs_command.py — Unit tests for the ``logs`` CLI command
Description:
    Verifies the Python-native tail used by ``wood-league-worker logs``
    works on any platform without shelling out to a ``tail`` binary.
    Regression coverage for issue #43 (WinError 2 on Windows).

Changelog:
    2026-05-12: Initial creation. Issue #43.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from local_worker.cli import _tail_lines, app


def test_tail_lines_returns_last_n_lines(tmp_path: Path) -> None:
    """The helper must return only the last ``count`` lines, in order."""
    log = tmp_path / "worker.log"
    log.write_text("\n".join(f"line {i}" for i in range(1, 101)) + "\n", encoding="utf-8")
    result = _tail_lines(log, 10)
    assert len(result) == 10
    assert result[0].strip() == "line 91"
    assert result[-1].strip() == "line 100"


def test_tail_lines_handles_short_files(tmp_path: Path) -> None:
    """Requesting more lines than exist must return everything."""
    log = tmp_path / "worker.log"
    log.write_text("only one line\n", encoding="utf-8")
    result = _tail_lines(log, 10)
    assert [line.strip() for line in result] == ["only one line"]


def test_tail_lines_zero_count(tmp_path: Path) -> None:
    """A non-positive count is a no-op."""
    log = tmp_path / "worker.log"
    log.write_text("a\nb\n", encoding="utf-8")
    assert _tail_lines(log, 0) == []
    assert _tail_lines(log, -5) == []


def test_logs_command_prints_tail_without_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: ``logs --tail`` writes the last N lines to stdout."""
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    log = tmp_path / "worker.log"
    log.write_text("\n".join(f"row {i}" for i in range(1, 21)) + "\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["logs", "--tail", "5"])
    assert result.exit_code == 0, result.output
    # Last five rows should appear; earlier rows should not.
    assert "row 20" in result.output
    assert "row 16" in result.output
    assert "row 10" not in result.output


def test_logs_command_handles_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing log file should produce a friendly message, not a crash."""
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0
    assert "does not exist yet" in result.output
