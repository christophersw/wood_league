"""Per-engine log routing for the vast fan-out."""
from loguru import logger

from local_worker.logging_setup import configure_logging


def test_basename_routes_filename(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WLW_LOG_BASENAME", "stockfish")
    monkeypatch.setenv("WLW_LOG_APPEND", "1")
    log_file = configure_logging(level="INFO", reset_file=True)
    assert log_file == tmp_path / "stockfish.log"
    logger.info("hello-sf")
    logger.complete()
    assert "hello-sf" in (tmp_path / "stockfish.log").read_text()


def test_append_mode_preserves_prior_content(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("WLW_LOG_BASENAME", "stockfish")
    monkeypatch.setenv("WLW_LOG_APPEND", "1")
    target = tmp_path / "stockfish.log"
    target.write_text("PRIOR-LINE\n")
    configure_logging(level="INFO", reset_file=True)
    logger.info("second-proc")
    logger.complete()
    body = target.read_text()
    assert "PRIOR-LINE" in body and "second-proc" in body


def test_default_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("WLW_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("WLW_LOG_BASENAME", raising=False)
    monkeypatch.delenv("WLW_LOG_APPEND", raising=False)
    log_file = configure_logging(level="INFO", reset_file=True)
    assert log_file == tmp_path / "worker.log"
