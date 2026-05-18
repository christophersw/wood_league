"""
Title: test_pytest_db_guard.py — Unit tests for the test-DB safety guard

Description:
    Pure-Python tests for _pytest_db_guard.assert_test_db_safe (no
    Django, no DB). The suite must only ever connect to sqlite or the
    explicitly declared TEST_DATABASE_URL — never the prod DATABASE_URL
    that .env may carry (issue #147 — guards the #9 leak from
    recurring; prod + test are both Railway, so the discriminator is a
    distinct variable name, not host matching).

Changelog:
    2026-05-17: Initial creation (issue #147).
    2026-05-17: Rework for TEST_DATABASE_URL-based policy.
"""
from __future__ import annotations

import pytest

from _pytest_db_guard import ProdDatabaseGuardError, assert_test_db_safe

_PROD = "postgres://u:p@prod.example.rlwy.net:5432/railway"
_TEST = "postgres://u:p@test.example.rlwy.net:5432/railway_test"


def _call(**overrides):
    """Invoke the guard with safe defaults overridden per test.

    Parameters:
        overrides: any of database_url / test_database_url /
            allow_override to replace the defaults.

    Returns:
        None: propagates ProdDatabaseGuardError if the guard rejects.
    """
    kwargs = dict(
        database_url="sqlite:///:memory:",
        test_database_url="",
        allow_override=False,
    )
    kwargs.update(overrides)
    assert_test_db_safe(**kwargs)


def test_sqlite_default_is_safe():
    """The conftest sqlite in-memory default is allowed."""
    _call(database_url="sqlite:///:memory:")


def test_effective_equals_declared_test_db_is_safe():
    """DATABASE_URL exactly equal to TEST_DATABASE_URL is allowed."""
    _call(database_url=_TEST, test_database_url=_TEST)


def test_nonsqlite_without_test_database_url_is_blocked():
    """A non-sqlite DB with no TEST_DATABASE_URL declared is blocked."""
    with pytest.raises(ProdDatabaseGuardError):
        _call(database_url=_PROD, test_database_url="")


def test_database_url_mismatching_test_url_is_blocked():
    """Prod-ish URL while TEST_DATABASE_URL points elsewhere is blocked.

    This is the look-alike-Railway case: even though both are rlwy.net
    Postgres, only an exact match to the declared test URL passes.
    """
    with pytest.raises(ProdDatabaseGuardError):
        _call(database_url=_PROD, test_database_url=_TEST)


def test_override_bypasses_everything():
    """The documented override env var bypasses the guard."""
    _call(database_url=_PROD, test_database_url="", allow_override=True)
