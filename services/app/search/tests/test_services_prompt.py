"""
Title: test_services_prompt.py — Assert new AI prompt directives are present
Description: String-match checks that the system prompt assembled by
    generate_search_plan teaches self-reference, name mapping, and club
    vocabulary rules.
Changelog:
    2026-05-20: Initial creation (#162).
"""
import pytest

from search import services


@pytest.mark.django_db
def test_schema_context_mentions_club_vocab():
    text = services._schema_context()
    lower = text.lower()
    assert "club games" in lower
    assert "club member" in lower or "club players" in lower


@pytest.mark.django_db
def test_schema_context_mentions_self_reference():
    text = services._schema_context()
    lower = text.lower()
    # Must teach the AI that I/me/my/mine refer to the current user
    assert "current_user_username" in lower
    assert "my" in lower or "mine" in lower


@pytest.mark.django_db
def test_generate_search_plan_threads_current_user(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):
                return {"content": [{"type": "text",
                    "text": '{"sql_query": "SELECT id, slug FROM games LIMIT 1", "reasoning": "ok"}'}]}

        return R()

    monkeypatch.setattr(services.requests, "post", fake_post)
    monkeypatch.setattr(services.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)

    services.generate_search_plan("show my games", current_user_username="chris")

    user_msg = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "chris" in user_msg.lower()


@pytest.mark.django_db
def test_generate_search_plan_anonymous_omits_user_marker(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):
                return {"content": [{"type": "text",
                    "text": '{"sql_query": "SELECT id, slug FROM games LIMIT 1", "reasoning": "ok"}'}]}

        return R()

    monkeypatch.setattr(services.requests, "post", fake_post)
    monkeypatch.setattr(services.settings, "ANTHROPIC_API_KEY", "test-key", raising=False)

    services.generate_search_plan("show recent games", current_user_username=None)
    user_msg = captured["payload"]["messages"][0]["content"][0]["text"]
    # When no current user, the payload's user message should not carry
    # a current_user_username marker
    assert "current_user_username" not in user_msg.lower()
