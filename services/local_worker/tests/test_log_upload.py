"""
Title: test_log_upload.py — Worker log-upload module tests
Description:
    Covers :func:`local_worker.log_upload.upload_log` and the crash hook
    installed by :func:`install_crash_hook`. Network calls are stubbed
    via monkeypatch; the goal is to confirm the multipart payload shape
    and the fail-soft semantics.

Changelog:
    2026-05-13 (#52): Initial creation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from local_worker import _log_upload_meta, log_upload
from local_worker.config import Settings


def _seed_log(tmp_path: Path, body: bytes = b'session log line\n') -> Path:
    """Write a fake worker.log under the directory and return its path."""
    log_path = tmp_path / 'worker.log'
    log_path.write_bytes(body)
    return log_path


def _stub_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``detect_environment`` with a deterministic dict."""
    monkeypatch.setattr(
        _log_upload_meta,
        'detect_environment',
        lambda: {
            'host': {'system': 'Darwin', 'machine': 'arm64'},
            'python': {'version': '3.12.4'},
            'engines': {'stockfish': {'path': '/usr/bin/stockfish'}},
        },
    )


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``load_settings`` with a configured fake."""
    monkeypatch.setattr(
        log_upload,
        'load_settings',
        lambda: Settings(api_url='https://app.test', api_key='secret-key', worker_id='wid'),
    )


def test_upload_log_posts_multipart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``upload_log`` POSTs the file + metadata to the right URL."""
    monkeypatch.setenv('WLW_LOG_DIR', str(tmp_path))
    _seed_log(tmp_path)
    _stub_environment(monkeypatch)
    _stub_settings(monkeypatch)
    captured: dict[str, Any] = {}

    class _FakeResponse:
        status_code = 201

        @staticmethod
        def json() -> dict[str, Any]:
            return {'id': 42, 'bucket_key': 'h/2026.log'}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        captured['url'] = url
        captured.update(kwargs)
        return _FakeResponse()

    monkeypatch.setattr(httpx, 'post', fake_post)
    upload_id = log_upload.upload_log('manual', note='please help')

    assert upload_id == 42
    assert captured['url'].endswith('/api/v1/worker/logs/')
    assert captured['headers']['X-Api-Key'] == 'secret-key'
    assert captured['data']['note'] == 'please help'
    import json as _json

    metadata = _json.loads(captured['data']['metadata'])
    assert metadata['reason'] == 'manual'
    assert metadata['host_summary']['system'] == 'Darwin'
    assert 'log' in captured['files']


def test_upload_log_crash_includes_force_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash upload appends ``?force=true`` to bypass the cooldown."""
    monkeypatch.setenv('WLW_LOG_DIR', str(tmp_path))
    _seed_log(tmp_path)
    _stub_environment(monkeypatch)
    _stub_settings(monkeypatch)
    captured: dict[str, Any] = {}

    class _FakeResponse:
        status_code = 201

        @staticmethod
        def json() -> dict[str, Any]:
            return {'id': 7}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        captured['url'] = url
        return _FakeResponse()

    monkeypatch.setattr(httpx, 'post', fake_post)
    log_upload.upload_log('crash')
    assert captured['url'].endswith('/api/v1/worker/logs/?force=true')


def test_upload_log_returns_minus_one_on_network_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A network error must not raise; it returns -1."""
    monkeypatch.setenv('WLW_LOG_DIR', str(tmp_path))
    _seed_log(tmp_path)
    _stub_environment(monkeypatch)
    _stub_settings(monkeypatch)

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise httpx.ConnectError('nope')

    monkeypatch.setattr(httpx, 'post', boom)
    assert log_upload.upload_log('manual') == -1


def test_upload_log_returns_minus_one_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An un-configured worker (no api_url/api_key) short-circuits to -1."""
    monkeypatch.setattr(log_upload, 'load_settings', lambda: Settings())
    assert log_upload.upload_log('manual') == -1


def test_upload_log_returns_minus_one_when_log_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing ``worker.log`` short-circuits to -1 (does not raise)."""
    monkeypatch.setenv('WLW_LOG_DIR', str(tmp_path))
    _stub_settings(monkeypatch)
    assert log_upload.upload_log('manual') == -1


def test_upload_log_returns_minus_one_on_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-201 response is treated as failure."""
    monkeypatch.setenv('WLW_LOG_DIR', str(tmp_path))
    _seed_log(tmp_path)
    _stub_environment(monkeypatch)
    _stub_settings(monkeypatch)

    class _FakeResponse:
        status_code = 429
        text = 'too many'

    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: _FakeResponse())
    assert log_upload.upload_log('manual') == -1


def test_install_crash_hook_replaces_excepthook(monkeypatch: pytest.MonkeyPatch) -> None:
    """``install_crash_hook`` installs a custom ``sys.excepthook``."""
    import sys

    original = sys.excepthook
    try:
        log_upload.install_crash_hook()
        assert sys.excepthook is not original
    finally:
        sys.excepthook = original
