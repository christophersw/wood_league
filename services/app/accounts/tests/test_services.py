"""
Title: test_services.py — accounts.services unit tests
Description: Tests resolve_current_player maps a Django user to a Player.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from accounts.models import User
from accounts.services import resolve_current_player
from players.models import Player


@pytest.mark.django_db
def test_resolve_returns_player_when_email_matches():
    user = User.objects.create_user(email="chris@example.com", password="x")
    player = Player.objects.create(
        username="chris", display_name="Chris", email="chris@example.com",
    )
    assert resolve_current_player(user) == player


@pytest.mark.django_db
def test_resolve_returns_none_when_no_player():
    user = User.objects.create_user(email="ghost@example.com", password="x")
    assert resolve_current_player(user) is None


def test_resolve_returns_none_for_anonymous():
    class Anon:
        is_authenticated = False
        email = ""

    assert resolve_current_player(Anon()) is None
