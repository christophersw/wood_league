"""
Title: conftest.py — Pytest root configuration for Django app
Description:
    Configures Django settings before test collection to prevent
    AppRegistryNotReady errors when model imports occur during collection.
    Loads services/app/.env.test if present, otherwise falls back to .env,
    and injects safe test-only defaults for SECRET_KEY, ALLOWED_HOSTS, and
    DEBUG so the suite runs without external setup. DEBUG=True is enforced
    so SECURE_SSL_REDIRECT (which only activates when DEBUG is False) does
    not 301-redirect Django test-client requests.

Changelog:
    2026-05-08: Created to fix AppRegistryNotReady in api/tests/
    2026-05-11: Auto-load .env/.env.test, inject test defaults, and force
                DEBUG=True so the test client isn't 301-redirected.
    2026-05-17 (#147): Hard guard — abort if the resolved DB looks like
                production (prevents the #9 .env-fallback leak).
"""

import os
from pathlib import Path

import django


def _load_env_file(name):
    """Populate os.environ with keys from services/app/<name> (if present).

    Parameters:
        name (str): Filename relative to this conftest's directory
            (typically ".env.test" or ".env").

    Returns:
        bool: True if the file was found and loaded, False otherwise.

    Side effects:
        Calls os.environ.setdefault for each key found, so existing process
        environment variables take precedence over values from the file.
    """
    env_path = Path(__file__).resolve().parent / name
    if not env_path.is_file():
        return False
    from decouple import RepositoryEnv

    for key, value in RepositoryEnv(str(env_path)).data.items():
        os.environ.setdefault(key, value)
    return True


def _apply_test_defaults():
    """Inject safe test-only defaults for any required env vars still unset.

    Parameters:
        None

    Returns:
        None

    Side effects:
        Sets SECRET_KEY (placeholder), ALLOWED_HOSTS, and DATABASE_URL
        (SQLite in-memory) if not already configured by an env file. Forces
        DEBUG=True regardless of upstream config so SECURE_SSL_REDIRECT does
        not bounce the Django test client.
    """
    os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
    os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
    os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
    # Always force DEBUG=True for tests so SECURE_SSL_REDIRECT (which
    # activates when DEBUG is False) doesn't 301-redirect test requests.
    os.environ["DEBUG"] = "True"


def pytest_configure(config):
    """Configure Django before pytest collects any test modules.

    Parameters:
        config: The pytest Config object (provided by the pytest hook system).

    Returns:
        None

    Side effects:
        Sets DJANGO_SETTINGS_MODULE, loads .env.test (preferred) or .env,
        applies safe test defaults, then calls django.setup() to initialise
        the app registry so model imports during collection succeed.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    env_test_loaded = _load_env_file(".env.test")
    if not env_test_loaded:
        _load_env_file(".env")
    _apply_test_defaults()

    # Hard guard: never let the suite run against production. The .env
    # fallback + setdefault could otherwise point tests at the live DB
    # and leak fixture rows into it (issue #9; guard is #147).
    import pytest

    from _pytest_db_guard import (
        OVERRIDE_ENV,
        ProdDatabaseGuardError,
        assert_test_db_safe,
    )

    try:
        assert_test_db_safe(
            database_url=os.environ.get("DATABASE_URL", ""),
            db_host=os.environ.get("DB_HOST", ""),
            env_test_loaded=env_test_loaded,
            allow_override=os.environ.get(OVERRIDE_ENV) == "1",
        )
    except ProdDatabaseGuardError as exc:
        raise pytest.UsageError(str(exc)) from exc

    django.setup()
