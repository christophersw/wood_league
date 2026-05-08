"""
Title: sync_service.py — Chess.com game sync service
Description:
    Fetches and persists Chess.com game archives for a list of usernames.
    Parameterized via constructor — no direct config module dependency.

Changelog:
    2026-05-07: Merged from dispatchers and stockfish_pipeline into shared library
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import io

import chess.pgn
from sqlalchemy import select

from wood_league_shared.storage.database import get_session, init_db
from wood_league_shared.ingest.chesscom_client import ChessComClient
from wood_league_shared.storage.models import Game, GameParticipant, Player


@dataclass
class SyncStats:
    """Tracks statistics from a single player sync operation.

    Attributes:
        username (str): The player username that was synced.
        inserted (int): Count of newly inserted games.
        updated (int): Count of updated games.
        archives_scanned (int): Count of monthly archives examined.
        inserted_game_ids (list[str]): IDs of newly inserted games.
    """

    username: str
    inserted: int = 0
    updated: int = 0
    archives_scanned: int = 0
    inserted_game_ids: list[str] = field(default_factory=list)


class ChessComSyncService:
    """Syncs Chess.com game data for one or more players into the database.

    Parameters:
        ingest_month_limit (int): Maximum number of months of history to import.
            Use 0 for unlimited. Defaults to 24.
        user_agent (str | None): Optional User-Agent string for API requests.
    """

    def __init__(
        self,
        *,
        ingest_month_limit: int = 24,
        user_agent: str | None = None,
    ) -> None:
        self._ingest_month_limit = ingest_month_limit
        self._client = ChessComClient(user_agent=user_agent)
        init_db()

    def sync_many(self, usernames: list[str]) -> list[SyncStats]:
        """Sync multiple players in sequence.

        Parameters:
            usernames (list[str]): Chess.com usernames to sync.

        Returns:
            list[SyncStats]: One SyncStats entry per username.
        """
        return [self.sync_player(username) for username in usernames]

    def sync_player(self, username: str) -> SyncStats:
        """Fetch and persist all in-scope games for a single player.

        Parameters:
            username (str): The Chess.com username to sync.

        Returns:
            SyncStats: Summary of inserted/updated counts and scanned archives.

        Side effects:
            Writes Player, Game, and GameParticipant rows to the database.
        """
        username = username.lower().strip()
        stats = SyncStats(username=username)

        with get_session() as session:
            player = session.scalar(select(Player).where(Player.username == username))
            if player is None:
                player = Player(username=username, display_name=username)
                session.add(player)
                session.flush()

            archives = self._client.get_archives(username)
            archives = [a for a in archives if self._archive_in_scope(a)]
            stats.archives_scanned = len(archives)

            for archive_url in archives:
                for payload in self._client.get_games_for_archive(archive_url):
                    changed, game_id = self._upsert_game(session, player, payload)
                    if changed == "inserted":
                        stats.inserted += 1
                        stats.inserted_game_ids.append(game_id)
                    elif changed == "updated":
                        stats.updated += 1

            session.commit()

        return stats

    def _archive_in_scope(self, archive_url: str) -> bool:
        """Return True if the archive is within the configured month limit.

        Parameters:
            archive_url (str): The monthly archive URL to check.

        Returns:
            bool: True if the archive should be processed, False otherwise.
        """
        limit = self._ingest_month_limit
        if limit <= 0:
            return True

        parts = archive_url.rstrip("/").split("/")
        if len(parts) < 2:
            return True

        try:
            year = int(parts[-2])
            month = int(parts[-1])
            archive_dt = datetime(year, month, 1, tzinfo=UTC)
        except ValueError:
            return True

        now = datetime.now(UTC)
        months_old = (now.year - archive_dt.year) * 12 + (now.month - archive_dt.month)
        return months_old <= limit

    def _upsert_game(self, session, player: Player, payload: dict) -> tuple[str, str]:
        """Insert or update a game and its participant record from an API payload.

        Parameters:
            session: SQLAlchemy session to use for database operations.
            player (Player): The player record for whom the game is being synced.
            payload (dict): Raw game payload dict from the Chess.com API.

        Returns:
            tuple[str, str]: ("inserted" | "updated", game_id)
        """
        game_id = payload.get("uuid") or self._stable_game_id(payload)
        game = session.get(Game, game_id)
        created = game is None
        if created:
            game = Game(id=game_id)
            session.add(game)

        white = payload.get("white", {})
        black = payload.get("black", {})
        white_user = (white.get("username") or "").lower()
        black_user = (black.get("username") or "").lower()

        if white_user == player.username:
            is_white = True
        elif black_user == player.username:
            is_white = False
        else:
            is_white = True

        my_side = white if is_white else black
        opp_side = black if is_white else white

        result = self._normalize_result(my_side.get("result", ""))
        played_at = datetime.fromtimestamp(int(payload.get("end_time", 0)), tz=UTC)
        result_pgn = payload.get("pgn", "")
        result_header = self._result_from_pgn(result_pgn)
        opening_name, eco_code = self._opening_from_pgn(result_pgn)

        game.played_at = played_at
        game.time_control = payload.get("time_control", "")
        game.white_username = white_user or None
        game.black_username = black_user or None
        game.white_rating = self._safe_int(white.get("rating"))
        game.black_rating = self._safe_int(black.get("rating"))
        game.result_pgn = result_header
        if result_header == "1-0":
            game.winner_username = white_user or None
        elif result_header == "0-1":
            game.winner_username = black_user or None
        else:
            game.winner_username = None
        game.eco_code = eco_code
        game.opening_name = opening_name
        game.lichess_opening = None
        game.pgn = result_pgn

        # Assign slug once on creation (not on updates, to keep URLs stable)
        if created and game.slug is None:
            game.slug = self._build_slug(session, white_user or "unknown", black_user or "unknown", played_at)

        self._upsert_participant(
            session=session,
            game_id=game_id,
            player=player,
            color=("White" if is_white else "Black"),
            opponent_username=(opp_side.get("username") or "unknown").lower(),
            player_rating=self._safe_int(my_side.get("rating")),
            opponent_rating=self._safe_int(opp_side.get("rating")),
            result=result,
        )

        return ("inserted" if created else "updated", game_id)

    @staticmethod
    def _upsert_participant(
        session,
        *,
        game_id: str,
        player: Player,
        color: str,
        opponent_username: str,
        player_rating: int | None,
        opponent_rating: int | None,
        result: str,
    ) -> None:
        """Insert or update a GameParticipant record.

        Parameters:
            session: SQLAlchemy session for database access.
            game_id (str): The game's primary key.
            player (Player): The player ORM object.
            color (str): "White" or "Black".
            opponent_username (str): Lowercase opponent username.
            player_rating (int | None): Rated ELO of the player, or None.
            opponent_rating (int | None): Rated ELO of the opponent, or None.
            result (str): "Win", "Loss", or "Draw".

        Returns:
            None
        """
        participant = session.scalar(
            select(GameParticipant).where(
                GameParticipant.game_id == game_id,
                GameParticipant.player_id == player.id,
            )
        )
        if participant is None:
            participant = GameParticipant(game_id=game_id, player_id=player.id)
            session.add(participant)

        participant.color = color
        participant.opponent_username = opponent_username
        participant.player_rating = player_rating
        participant.opponent_rating = opponent_rating
        participant.result = result

    @staticmethod
    def _safe_int(value) -> int | None:
        """Convert a value to int, returning None on failure.

        Parameters:
            value: Any value to attempt int conversion on.

        Returns:
            int | None: Integer value or None if conversion fails.
        """
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _stable_game_id(payload: dict) -> str:
        """Generate a stable game ID from payload fields when UUID is absent.

        Parameters:
            payload (dict): Raw game payload from the Chess.com API.

        Returns:
            str: A 24-character hex string derived from game content.
        """
        raw = f"{payload.get('url', '')}|{payload.get('end_time', '')}|{payload.get('pgn', '')[:120]}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _slugify(value: str) -> str:
        """Convert a string to a URL-safe slug.

        Parameters:
            value (str): The string to slugify.

        Returns:
            str: Lowercased, hyphen-separated slug with non-alphanumeric chars removed.
        """
        value = value.lower()
        value = re.sub(r"[^a-z0-9]+", "-", value)
        return value.strip("-")

    def _build_slug(self, session, white: str, black: str, played_at: datetime) -> str:
        """Return a unique slug like 'alice-vs-bob-2026-04-28' (or '-2', '-3' suffix).

        Parameters:
            session: SQLAlchemy session for querying existing slugs.
            white (str): White player username.
            black (str): Black player username.
            played_at (datetime): When the game was played.

        Returns:
            str: A unique slug string for the game.
        """
        date_str = played_at.strftime("%Y-%m-%d")
        base = f"{self._slugify(white)}-vs-{self._slugify(black)}-{date_str}"

        existing = session.scalars(
            select(Game.slug).where(Game.slug.like(f"{base}%"))
        ).all()

        if not existing:
            return base

        used = set(existing)
        counter = 2
        while f"{base}-{counter}" in used:
            counter += 1
        return f"{base}-{counter}"

    @staticmethod
    def _normalize_result(value: str) -> str:
        """Map a Chess.com result string to a canonical Win/Draw/Loss label.

        Parameters:
            value (str): The raw result string from the Chess.com API.

        Returns:
            str: One of "Win", "Draw", or "Loss".
        """
        draw_results = {
            "agreed",
            "repetition",
            "stalemate",
            "insufficient",
            "50move",
            "timevsinsufficient",
        }
        loss_results = {"checkmated", "resigned", "timeout", "lose", "abandoned"}

        if value == "win":
            return "Win"
        if value in draw_results:
            return "Draw"
        if value in loss_results:
            return "Loss"
        return "Draw"

    @staticmethod
    def _result_from_pgn(pgn: str) -> str | None:
        """Extract the Result header from a PGN string.

        Parameters:
            pgn (str): PGN text to parse.

        Returns:
            str | None: The Result header value (e.g. "1-0"), or None if not found.
        """
        if not pgn.strip():
            return None

        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return None

        value = (game.headers.get("Result") or "").strip()
        return value or None

    @staticmethod
    def _opening_from_pgn(pgn: str) -> tuple[str, str]:
        """Extract the opening name and ECO code from a PGN string.

        Parameters:
            pgn (str): PGN text to parse.

        Returns:
            tuple[str, str]: (opening_name, eco_code). Falls back to first 5 moves
                if no Opening header is present.
        """
        if not pgn.strip():
            return "Unknown", ""

        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return "Unknown", ""

        headers = game.headers
        opening_name = headers.get("Opening", "").strip()
        eco = headers.get("ECO", "").strip()

        if opening_name:
            return opening_name, eco

        board = game.board()
        sans: list[str] = []
        for idx, move in enumerate(game.mainline_moves(), start=1):
            sans.append(board.san(move))
            board.push(move)
            if idx >= 5:
                break

        return (" ".join(sans) if sans else "Unknown"), eco
