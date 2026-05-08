from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


class ChessComClient:
    def __init__(self, user_agent: str | None = None) -> None:
        self._user_agent = user_agent or os.environ.get(
            "CHESS_COM_USER_AGENT", "wood-league-dispatchers/0.1 (+runpod dispatcher)"
        )

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_archives(self, username: str) -> list[str]:
        endpoint = f"https://api.chess.com/pub/player/{username}/games/archives"
        payload = self._get_json(endpoint)
        return payload.get("archives", [])

    def get_games_for_archive(self, archive_url: str) -> list[dict[str, Any]]:
        payload = self._get_json(archive_url)
        return payload.get("games", [])
