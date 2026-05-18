"""
Title: _pytest_db_guard.py — Tests connect only to TEST_DATABASE_URL

Description:
    conftest.py used to fall back to the main .env (production
    DATABASE_URL) when services/app/.env.test was absent, and
    _apply_test_defaults() used setdefault so it could not override
    that prod URL — letting the suite run against production and leak
    test-* fixture rows into the live DB (issue #9; guard is #147).

    Host/provider matching is unreliable here because the prod and
    test databases are both Railway Postgres with near-identical
    connection strings. So the discriminator is a distinct variable
    name, not pattern-matching: the test database is configured via
    TEST_DATABASE_URL (set in services/app/.env.test). conftest forces
    the effective DATABASE_URL to TEST_DATABASE_URL (or the sqlite
    in-memory default) and never to the prod DATABASE_URL that .env
    may carry.

    assert_test_db_safe() is a pure decision function (no Django, no
    DB, no I/O) — a tripwire that fails collection if the effective
    DATABASE_URL is anything other than sqlite or the explicitly
    declared TEST_DATABASE_URL.

    Policy:
      - sqlite (the safe default) -> always allowed.
      - DATABASE_URL exactly equal to TEST_DATABASE_URL -> allowed.
      - anything else -> blocked (no TEST_DATABASE_URL declared, or
        DATABASE_URL points somewhere else entirely).
      - override: WL_ALLOW_PROD_DB_IN_TESTS=1 bypasses (documented
        escape hatch).

Changelog:
    2026-05-17: Initial creation (issue #147).
    2026-05-17: Rework around TEST_DATABASE_URL — drop fragile host
                marker matching (prod + test are both Railway, #147).
"""
from __future__ import annotations

OVERRIDE_ENV = "WL_ALLOW_PROD_DB_IN_TESTS"


class ProdDatabaseGuardError(RuntimeError):
    """Raised when the test session would hit a non-test database."""


def assert_test_db_safe(
    *,
    database_url: str,
    test_database_url: str,
    allow_override: bool,
) -> None:
    """Raise unless tests target sqlite or the declared test DB.

    Parameters:
        database_url (str): the DATABASE_URL the suite will actually
            connect with (conftest sets this from TEST_DATABASE_URL or
            the sqlite default).
        test_database_url (str): the value of TEST_DATABASE_URL ("" if
            unset) — the explicitly declared test database.
        allow_override (bool): True if WL_ALLOW_PROD_DB_IN_TESTS=1,
            bypassing the guard entirely.

    Returns:
        None: returns normally when the target is test-safe.

    Raises:
        ProdDatabaseGuardError: when the effective DATABASE_URL is
            neither sqlite nor exactly the declared TEST_DATABASE_URL.
    """
    if allow_override:
        return

    effective = (database_url or "").strip()
    if effective.startswith("sqlite"):
        return

    declared = (test_database_url or "").strip()
    if declared and effective == declared:
        return

    raise ProdDatabaseGuardError(
        "Refusing to run tests: the effective DATABASE_URL is neither "
        "sqlite nor the declared TEST_DATABASE_URL. Tests must never "
        "touch the production database (see issue #9). Set "
        "TEST_DATABASE_URL in services/app/.env.test to a dedicated "
        f"test database, or set {OVERRIDE_ENV}=1 to bypass deliberately."
    )
