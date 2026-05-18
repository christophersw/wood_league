"""
Title: test_pytest_db_guard.py — Unit tests for the test-DB safety guard

Description:
    Pure-Python tests for _pytest_db_guard.assert_test_db_safe (no
    Django, no DB). Covers the policy that prevents the suite running
    against production (issue #147 — guards the #9 leak from recurring).

Changelog:
    2026-05-17: Initial creation (issue #147).
"""
from __future__ import annotations

import pytest

from _pytest_db_guard import ProdDatabaseGuardError, assert_test_db_safe


def _call(**overrides):
    """Invoke the guard with safe defaults overridden per test.

    Parameters:
        overrides: any of database_url / db_host / env_test_loaded /
            allow_override to replace the defaults.

    Returns:
        None: propagates ProdDatabaseGuardError if the guard rejects.
    """
    kwargs = dict(
        database_url="",
        db_host="",
        env_test_loaded=False,
        allow_override=False,
    )
    kwargs.update(overrides)
    assert_test_db_safe(**kwargs)


def test_sqlite_is_always_safe():
    """The conftest default (sqlite in-memory) is allowed."""
    _call(database_url="sqlite:///:memory:")


def test_localhost_postgres_is_safe():
    """A local dev Postgres is allowed."""
    _call(database_url="postgres://u:p@localhost:5432/wl")


def test_blank_db_host_is_safe():
    """No URL and no host (pure defaults) is allowed."""
    _call(database_url="", db_host="")


def test_railway_prod_host_is_blocked_even_with_env_test():
    """A prod-marker host is blocked even if .env.test set it."""
    with pytest.raises(ProdDatabaseGuardError):
        _call(
            database_url="postgres://u:p@postgres.railway.internal:5432/db",
            env_test_loaded=True,
        )


def test_nonlocal_host_blocked_when_env_test_missing():
    """The .env fallback path (no .env.test, remote host) is blocked."""
    with pytest.raises(ProdDatabaseGuardError):
        _call(
            database_url="postgres://u:p@db.example.com:5432/wl",
            env_test_loaded=False,
        )


def test_nonlocal_dev_host_allowed_via_env_test():
    """An explicit .env.test remote dev DB (non-prod marker) is allowed."""
    _call(
        database_url="postgres://u:p@turntable.devbox.lan:5432/wl_test",
        env_test_loaded=True,
    )


def test_override_bypasses_everything():
    """The documented override env var bypasses the guard."""
    _call(
        database_url="postgres://u:p@postgres.railway.internal:5432/db",
        env_test_loaded=False,
        allow_override=True,
    )
