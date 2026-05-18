"""
Title: test_run_command.py — Tests for the ``run`` command's self-stop hook
Description:
    Verifies the post-drain RunPod self-stop hook fires only when enabled,
    that it resolves the pod id from settings or env, and that a missing
    pod id logs a warning instead of making an HTTP call. Also covers the
    --max-jobs CLI flag (E-T2).

Changelog:
    2026-05-14: Initial creation for issue #81.
    2026-05-16: Add --max-jobs / --batch-size CLI flag assertions (E-T2).
"""
from __future__ import annotations

import logging
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from local_worker.commands import run as run_cmd
from local_worker.config import Settings


def _settings(**overrides: Any) -> Settings:
    """Build a ``Settings`` instance with self-stop-relevant defaults filled in."""
    base: dict[str, Any] = dict(
        runpod_self_stop_enabled=False,
        runpod_api_key="",
        runpod_pod_id="",
    )
    base.update(overrides)
    return Settings(**base)


def test_maybe_stop_runpod_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag off, ``stop_self`` must not be called."""
    calls: list[tuple[str, str]] = []

    def _record_stop_call(pod_id: str, api_key: str) -> bool:
        calls.append((pod_id, api_key))
        return True

    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        _record_stop_call,
    )

    run_cmd._maybe_stop_runpod(
        _settings(runpod_self_stop_enabled=False, runpod_api_key="k", runpod_pod_id="p")
    )

    assert calls == []


def test_maybe_stop_runpod_calls_stop_with_resolved_pod_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabled + creds present → exactly one ``stop_self`` call with the pod id."""
    calls: list[tuple[str, str]] = []

    def _record_stop_call(pod_id: str, api_key: str) -> bool:
        calls.append((pod_id, api_key))
        return True

    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        _record_stop_call,
    )

    run_cmd._maybe_stop_runpod(
        _settings(
            runpod_self_stop_enabled=True,
            runpod_api_key="api-key-1",
            runpod_pod_id="pod-xyz",
        )
    )

    assert calls == [("pod-xyz", "api-key-1")]


def test_maybe_stop_runpod_resolves_pod_id_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no explicit pod id is set, the ``RUNPOD_POD_ID`` env var is used."""
    monkeypatch.setenv("RUNPOD_POD_ID", "pod-from-env")
    calls: list[tuple[str, str]] = []

    def _record_stop_call(pod_id: str, api_key: str) -> bool:
        calls.append((pod_id, api_key))
        return True

    monkeypatch.setattr(
        run_cmd,
        "stop_self",
        _record_stop_call,
    )

    run_cmd._maybe_stop_runpod(
        _settings(runpod_self_stop_enabled=True, runpod_api_key="api-key-1")
    )

    assert calls == [("pod-from-env", "api-key-1")]


def test_maybe_stop_runpod_warns_when_pod_id_unresolvable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Flag on + creds present but no pod id → log WARNING, no HTTP call."""
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    called = False

    def fake_stop(*_a: Any, **_kw: Any) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(run_cmd, "stop_self", fake_stop)

    with caplog.at_level(logging.WARNING, logger="local_worker.commands.run"):
        run_cmd._maybe_stop_runpod(
            _settings(runpod_self_stop_enabled=True, runpod_api_key="api-key-1")
        )

    assert called is False
    assert any("no pod id resolvable" in record.message for record in caplog.records)


def test_maybe_stop_runpod_warns_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Flag on but no api key → log WARNING, no HTTP call."""
    called = False

    def fake_stop(*_a: Any, **_kw: Any) -> bool:
        nonlocal called
        called = True
        return True

    monkeypatch.setattr(run_cmd, "stop_self", fake_stop)

    with caplog.at_level(logging.WARNING, logger="local_worker.commands.run"):
        run_cmd._maybe_stop_runpod(
            _settings(runpod_self_stop_enabled=True, runpod_pod_id="pod-xyz")
        )

    assert called is False
    assert any("WLW_RUNPOD_API_KEY" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# --max-jobs / --batch-size CLI option tests (E-T2)
# ---------------------------------------------------------------------------


def test_run_help_shows_max_jobs() -> None:
    """``run --help`` must advertise ``--max-jobs`` (E-T2 step 6).

    Confirms the Typer option was renamed correctly.
    """
    from local_worker.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert "--max-jobs" in result.output, (
        f"Expected --max-jobs in help output, got:\n{result.output}"
    )


def test_run_help_does_not_show_batch_size() -> None:
    """``run --help`` must NOT show ``--batch-size`` after the E-T2 rename."""
    from local_worker.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--help"])
    assert "--batch-size" not in result.output, (
        f"Expected --batch-size to be absent from help, got:\n{result.output}"
    )


def test_run_batch_size_flag_is_rejected() -> None:
    """``run --batch-size 10`` must exit non-zero (unknown option after rename)."""
    from local_worker.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["run", "--batch-size", "10"])
    assert result.exit_code != 0, (
        f"Expected non-zero exit for unknown --batch-size, got exit_code={result.exit_code}"
    )


def test_resolve_run_options_max_jobs_prompt_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """_resolve_run_options must use the new prompt text for max_jobs (E-T2 step 6).

    Monkeypatches questionary so no interactive terminal is needed.
    """
    prompts_seen: list[str] = []

    class _FakeQuestion:
        def __init__(self, text: str) -> None:
            prompts_seen.append(text)

        def ask(self) -> str:
            return ""  # blank → max_jobs = None

    class _FakeSelectQuestion:
        def ask(self) -> str:
            return "stockfish"

    # This test exercises the *interactive* prompt path; declare a TTY so
    # the #152 non-interactive guard doesn't short-circuit the prompts.
    monkeypatch.setattr(run_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(run_cmd.questionary, "text", lambda text, **_kw: _FakeQuestion(text))
    monkeypatch.setattr(run_cmd.questionary, "select", lambda *_a, **_kw: _FakeSelectQuestion())

    engines, max_jobs, batch_time = run_cmd._resolve_run_options(
        engine=None, max_jobs=None, batch_time=None
    )

    assert any("Max jobs this run?" in p for p in prompts_seen), (
        f"Expected max-jobs prompt text not found. Prompts seen: {prompts_seen}"
    )
    assert max_jobs is None
    assert engines == ["stockfish"]


def test_resolve_run_options_headless_skips_prompts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive (no TTY) with --engine given: no questionary
    prompt fires and missing max_jobs/batch_time default to None
    (run until queue empty), instead of aborting (#152)."""

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("questionary prompt fired in headless mode")

    monkeypatch.setattr(run_cmd.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(run_cmd.questionary, "select", _boom)
    monkeypatch.setattr(run_cmd.questionary, "text", _boom)

    engines, max_jobs, batch_time = run_cmd._resolve_run_options(
        engine="lc0", max_jobs=None, batch_time=None
    )

    assert engines == ["lc0"]
    assert max_jobs is None
    assert batch_time is None


def test_resolve_run_options_headless_requires_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive with no --engine: a clear typer.Exit(1), not a
    cryptic questionary 'Aborted.' (#152)."""

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("questionary prompt fired in headless mode")

    monkeypatch.setattr(run_cmd.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(run_cmd.questionary, "select", _boom)

    with pytest.raises(typer.Exit) as exc:
        run_cmd._resolve_run_options(engine=None, max_jobs=None, batch_time=None)
    assert exc.value.exit_code == 1


def test_resolve_run_options_headless_engine_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headless with --engine both expands to both engines, no prompt (#152)."""

    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("questionary prompt fired in headless mode")

    monkeypatch.setattr(run_cmd.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(run_cmd.questionary, "text", _boom)

    engines, max_jobs, batch_time = run_cmd._resolve_run_options(
        engine="both", max_jobs=5, batch_time=None
    )
    assert engines == ["stockfish", "lc0"]
    assert max_jobs == 5
    assert batch_time is None
