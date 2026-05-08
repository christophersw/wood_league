"""
Title: chesscom_client.py — Chess.com public API client
Description:
    Fetches game archives and game data from the Chess.com public API.
    Accepts user_agent as a constructor parameter; falls back to an env var
    or a default string. Has no dependency on service-specific config modules.

Changelog:
    2026-05-07: Merged from dispatchers and stockfish_pipeline into shared library
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


class ChessComClient:
    """Client for the Chess.com public API.

    Parameters:
        user_agent (str | None): Optional User-Agent header string.
            Falls back to the CHESS_COM_USER_AGENT env var, then a default value.
    """

    def __init__(self, user_agent: str | None = None) -> None:
        self._user_agent = user_agent or os.environ.get(
            "CHESS_COM_USER_AGENT", "wood-league/0.1"
        )

    def _get_json(self, url: str) -> dict[str, Any]:
        """Fetch a JSON response from the given URL.

        Parameters:
            url (str): The URL to request.

        Returns:
            dict[str, Any]: Parsed JSON response body.
        """
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
        """Return list of monthly archive URLs for a Chess.com player.

        Parameters:
            username (str): The Chess.com username to query.

        Returns:
            list[str]: List of monthly archive URL strings.
        """
        endpoint = f"https://api.chess.com/pub/player/{username}/games/archives"
        payload = self._get_json(endpoint)
        return payload.get("archives", [])

    def get_games_for_archive(self, archive_url: str) -> list[dict[str, Any]]:
        """Return list of game dicts for a given monthly archive URL.

        Parameters:
            archive_url (str): The monthly archive URL to fetch games from.

        Returns:
            list[dict[str, Any]]: List of game payload dictionaries.
        """
        payload = self._get_json(archive_url)
        return payload.get("games", [])
