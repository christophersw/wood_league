"""
Title: test_login_required_middleware.py — Auth-enforcement coverage
Description:
    Guards that LoginRequiredMiddleware redirects unauthenticated requests to
    the login page when AUTH_ENABLED is True, and that public auth paths stay
    exempt. The suite runs with AUTH_ENABLED forced False (see conftest, so the
    partials/view tests aren't bounced to login), which means the redirect path
    is otherwise never exercised; these tests flip the flag back on per-test to
    keep that enforcement under coverage.

Changelog:
    2026-05-29 (#226 review): Initial — restore auth-redirect coverage lost when
        conftest began forcing AUTH_ENABLED=False suite-wide.
"""
import pytest
from django.test import override_settings
from django.urls import reverse

pytestmark = pytest.mark.django_db


@override_settings(AUTH_ENABLED=True)
def test_unauthenticated_request_redirects_to_login(client):
    """An anonymous request to a protected page 302-redirects to the login URL.

    The middleware reads settings.AUTH_ENABLED at request time, so
    override_settings is sufficient to re-enable enforcement for this test.

    Params:
        client: Django test client with no authenticated user.
    """
    target = reverse("dashboard:index")
    resp = client.get(target)
    assert resp.status_code == 302, "protected page must redirect when auth is on"
    login_url = reverse("accounts:login")
    assert resp.url.startswith(login_url), f"expected redirect to {login_url}, got {resp.url}"
    assert f"next={target}" in resp.url, "redirect must preserve the ?next= target"


@override_settings(AUTH_ENABLED=True)
def test_public_login_path_is_not_redirected(client):
    """The login page itself is exempt and returns 200 even when auth is on.

    Params:
        client: Django test client with no authenticated user.
    """
    resp = client.get(reverse("accounts:login"))
    assert resp.status_code == 200, "login page must stay reachable without auth"
