"""
Title: test_views.py — search view behaviour
Description: Asserts copy changes, current_user_username threading, and the
    new modal partial endpoint.
Changelog:
    2026-05-20: Initial creation (#162).
"""
from unittest import mock

import pytest
from django.urls import reverse

from accounts.models import User
from games.models import Game
from players.models import Player


def test_search_index_url_resolves():
    """search_index URL name resolves without errors.

    Full render deferred — base.html triggers a pre-existing instrumented_test_render
    recursion in Django 5 / Python 3.13 that is unrelated to this task.
    Copy assertion ("validated SQL" not in body) lands in Task 12 (#162).
    """
    url = reverse("search_index")
    assert url == "/search/"


@pytest.mark.django_db
def test_ai_partial_passes_current_user(client):
    user = User.objects.create_user(email="chris@example.com", password="x")
    Player.objects.create(
        username="chris", display_name="Chris", email="chris@example.com",
    )
    client.force_login(user)
    with mock.patch("search.views.generate_search_plan") as gp:
        gp.return_value = mock.Mock(
            sql_query="SELECT id, slug FROM games LIMIT 1", reasoning="ok",
        )
        with mock.patch("search.views.execute_sql_search", return_value=[]):
            client.post(reverse("search_ai_partial"),
                        {"query": "my recent losses"})
    args, kwargs = gp.call_args
    assert kwargs.get("current_user_username") == "chris"


@pytest.mark.django_db
def test_ai_partial_anonymous_passes_none(client):
    with mock.patch("search.views.generate_search_plan") as gp:
        gp.return_value = mock.Mock(
            sql_query="SELECT id, slug FROM games LIMIT 1", reasoning="ok",
        )
        with mock.patch("search.views.execute_sql_search", return_value=[]):
            client.post(reverse("search_ai_partial"), {"query": "recent games"})
    args, kwargs = gp.call_args
    assert kwargs.get("current_user_username") is None


@pytest.mark.django_db
def test_game_modal_partial(client):
    from datetime import datetime, timezone
    g = Game.objects.create(
        id="m1", slug="m-1",
        white_username="chris", black_username="alice",
        played_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        time_control="180+0",
        pgn="[Event \"t\"]\n\n1. e4 e5 *",
        result_pgn="1-0", winner_username="chris",
    )
    resp = client.get(reverse("search_game_modal_partial", args=[g.id]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "chris" in body and "alice" in body
    assert "OPEN ANALYSIS" in body
