"""
Title: test_views.py — search view behaviour
Description: Asserts copy changes, current_user_username threading, and the
    new modal partial endpoint.
Changelog:
    2026-05-20: Initial creation (#162).
    2026-05-20: #169 — restore full-render test now that components/_modal.html
                no longer self-recurses via a mis-formatted {# #} comment.
"""
from unittest import mock

import pytest
from django.urls import reverse

from accounts.models import User
from games.models import Game
from players.models import Player


def test_search_index_url_resolves():
    """search_index URL name resolves to /search/."""
    url = reverse("search_index")
    assert url == "/search/"


@pytest.mark.django_db
def test_search_index_full_render(client):
    """GET /search/ renders the page through base.html without recursion (#169)."""
    resp = client.get("/search/", secure=True)
    assert resp.status_code == 200
    body = resp.content.decode()
    # Modal shell from base.html is present — proves _modal.html rendered once,
    # not in an infinite include loop.
    assert 'id="search-modal"' in body
    # Older copy must stay gone (#162 Task 12).
    assert "validated SQL" not in body


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
