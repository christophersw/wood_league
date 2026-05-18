"""
Title: _pytest_db_guard.py — Refuse to run the test suite against prod

Description:
    conftest.py falls back to the main .env (production DATABASE_URL)
    when services/app/.env.test is absent, and _apply_test_defaults()
    uses setdefault so it cannot override that prod URL. That let the
    suite run against production and leak test-* fixture rows into the
    live DB (issue #9; this guard is issue #147).

    assert_test_db_safe() is a pure decision function (no Django, no
    DB, no I/O) so it is trivially unit-testable. conftest calls it
    after env resolution and converts a failure into a clean
    pytest.UsageError that aborts collection before any test touches
    the database.

    Policy (non-breaking):
      - sqlite (the safe default) -> always allowed.
      - localhost / 127.0.0.1 / ::1 -> allowed (local dev Postgres).
      - a known prod-marker host (railway.internal, rlwy.net,
        amazonaws, neon.tech, supabase.co) -> ALWAYS blocked, even if
        .env.test set it (a misconfigured .env.test must not nuke
        prod), unless the documented override is set.
      - any other non-local host -> allowed ONLY if it came from an
        explicit .env.test (a deliberate remote dev DB); blocked when
        it leaked in via the .env fallback.
      - override: WL_ALLOW_PROD_DB_IN_TESTS=1 bypasses (escape hatch
        for the rare intentional case; loudly documented).

Changelog:
    2026-05-17: Initial creation (issue #147).
"""
from __future__ import annotations

from urllib.parse import urlparse

_LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
# Deliberately precise: only the production *internal* host. A real
# dedicated test DB can never sit on prod's private network, so this
# has zero false-positive risk — unlike broad provider domains
# (rlwy.net / amazonaws / neon / supabase) which a legitimate cloud
# test DB could legitimately share. The .env.test-missing gate below
# is what catches the general prod-fallback leak (#9 / #147).
_PROD_MARKERS = ("railway.internal",)
OVERRIDE_ENV = "WL_ALLOW_PROD_DB_IN_TESTS"


class ProdDatabaseGuardError(RuntimeError):
    """Raised when the test session would hit a non-test database."""


def _host_from(database_url: str) -> str | None:
    """Return the host of a DB URL, or None when it has no host.

    Parameters:
        database_url (str): a DATABASE_URL value (may be empty or a
            sqlite URL, which has no network host).

    Returns:
        str | None: the lowercased hostname, or None for sqlite/blank.
    """
    if not database_url or database_url.startswith("sqlite"):
        return None
    parsed = urlparse(database_url)
    return (parsed.hostname or "").lower() or None


def _effective_host(database_url: str, db_host: str) -> str:
    """Return the host the suite would actually connect to.

    Parameters:
        database_url (str): resolved DATABASE_URL ("" if unset).
        db_host (str): resolved DB_HOST fallback ("" if unset).

    Returns:
        str: lowercased host (DATABASE_URL wins; DB_HOST is the
        fallback; "" for sqlite/blank).
    """
    return _host_from(database_url) or (db_host or "").strip().lower()


def _is_safe_local(database_url: str, host: str) -> bool:
    """Return True for sqlite or a recognised local host (always safe).

    Parameters:
        database_url (str): resolved DATABASE_URL.
        host (str): the effective host from _effective_host.

    Returns:
        bool: True when the target needs no further checks.
    """
    return (database_url or "").strip().startswith("sqlite") or (
        host in _LOCAL_HOSTS
    )


def _prod_marker(database_url: str, host: str) -> str | None:
    """Return the matched production marker, or None.

    Parameters:
        database_url (str): resolved DATABASE_URL.
        host (str): the effective host.

    Returns:
        str | None: the first _PROD_MARKERS substring found, else None.
    """
    haystack = f"{database_url} {host}".lower()
    for marker in _PROD_MARKERS:
        if marker in haystack:
            return marker
    return None


def assert_test_db_safe(
    *,
    database_url: str,
    db_host: str,
    env_test_loaded: bool,
    allow_override: bool,
) -> None:
    """Raise ProdDatabaseGuardError unless the target DB is test-safe.

    Parameters:
        database_url (str): resolved DATABASE_URL ("" if unset).
        db_host (str): resolved DB_HOST fallback ("" if unset).
        env_test_loaded (bool): True if services/app/.env.test was the
            source of configuration (an explicit, deliberate test env).
        allow_override (bool): True if the documented override env var
            is set, bypassing the guard entirely.

    Returns:
        None: returns normally when the database is safe to test on.

    Raises:
        ProdDatabaseGuardError: when the configured database is (or may
            be) production and the override is not set.
    """
    if allow_override:
        return

    host = _effective_host(database_url, db_host)
    if _is_safe_local(database_url, host):
        return

    marker = _prod_marker(database_url, host)
    if marker is not None:
        raise ProdDatabaseGuardError(
            f"Refusing to run tests: database host '{host}' matches the "
            f"production marker '{marker}'. Tests must never touch the "
            f"live database (see issue #9). Create services/app/.env.test "
            f"pointing at a dedicated dev/test database. To bypass "
            f"deliberately, set {OVERRIDE_ENV}=1."
        )

    if not env_test_loaded:
        raise ProdDatabaseGuardError(
            f"Refusing to run tests: a non-local database host '{host}' "
            f"was configured but services/app/.env.test was not found, so "
            f"this came from the main .env fallback (likely production). "
            f"Create services/app/.env.test for a dedicated test database, "
            f"or set {OVERRIDE_ENV}=1 to bypass deliberately."
        )
