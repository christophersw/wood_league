"""
Title: test_dashboard_view.py — Tests for /admin/dashboard/
Description:
    Verifies the dashboard shell and its six HTMX partials each return
    200 to admin users, the page contains all six partial wrappers, the
    legacy /admin/diagnostics/ URL redirects to /admin/dashboard/, and
    non-admin users cannot access any of these endpoints.

Changelog:
    2026-05-14 (#106): Initial smoke tests for the wire-up slice.
"""
from __future__ import annotations

import uuid

import pytest
from django.urls import reverse

from accounts.models import User


def _make_user(role: str) -> User:
    """Create a test user with the given role."""
    return User.objects.create_user(
        email=f"{role}-dash-{uuid.uuid4().hex[:6]}@test",
        password="x",  # noqa: S106 — test-only
        role=role,
    )


@pytest.mark.django_db
def test_dashboard_shell_renders_for_admin(client):
    """The shell page returns 200 and contains all six partial wrappers."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:dashboard"))

    assert response.status_code == 200
    content = response.content.decode()
    for wrapper_id in (
        "dash-banner", "dash-workers", "dash-queues",
        "dash-throughput", "dash-recent", "dash-failures",
    ):
        assert f'id="{wrapper_id}"' in content


@pytest.mark.django_db
@pytest.mark.parametrize("name", [
    "dash_banner", "dash_workers", "dash_queues",
    "dash_throughput", "dash_recent", "dash_failures",
])
def test_each_partial_renders_for_admin(client, name):
    """Each of the six partial endpoints returns 200 for an admin."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse(f"analysis:{name}"))

    assert response.status_code == 200


@pytest.mark.django_db
def test_diagnostics_redirects_to_dashboard(client):
    """Legacy /admin/diagnostics/ URL 302s to /admin/dashboard/."""
    admin = _make_user("admin")
    client.force_login(admin)

    response = client.get(reverse("analysis:diagnostics"))

    assert response.status_code == 302
    assert response.url.endswith(reverse("analysis:dashboard"))


@pytest.mark.django_db
def test_dashboard_requires_admin(client):
    """Non-admin users get a redirect (login) on the dashboard URL."""
    player = _make_user("player")
    client.force_login(player)

    response = client.get(reverse("analysis:dashboard"))

    # staff_member_required redirects to admin login
    assert response.status_code == 302
