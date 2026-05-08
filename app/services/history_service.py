"""Game history service for retrieving player statistics, ratings, and opening distributions.

Fetches player game history from database with fallback to demo data, supporting ELO timeseries,
recent games with evaluations, and opening frequency analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import random

import pandas as pd
from sqlalchemy import and_, func, select

from app.storage.database import get_session, init_db
from app.storage.models import Game, GameAnalysis, GameParticipant, Player


@dataclass
class HistoryFilters:
    """Filter parameters for game history queries."""
    player: str
    lookback_days: int = 90
    recent_limit: int = 20


class HistoryService:
    """Retrieves player game history, ratings, and opening statistics."""
    def __init__(self) -> None:
        """Initialize with demo player names and database."""
        self._demo_players = ["alice", "bob", "carol", "dave"]
        init_db()

    def _has_real_data(self) -> bool:
        """Check if database contains actual player records."""
        with get_session() as session:
            count = session.scalar(select(func.count()).select_from(Player)) or 0
            return count > 0

    def list_players(self) -> list[str]:
        """List all players in database or return demo players if empty."""
        if self._has_real_data():
            with get_session() as session:
                rows = session.scalars(select(Player.username).order_by(Player.username)).all()
                if rows:
                    return list(rows)
        return self._demo_players

    def get_elo_timeseries(self, filters: HistoryFilters) -> pd.DataFrame:
        """Get player rating over time within lookback period."""
        if not self._has_real_data():
            return self._demo_elo_timeseries(filters)

        floor_date = datetime.utcnow().date() - timedelta(days=filters.lookback_days)
        with get_session() as session:
            rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username,
                    func.avg(GameParticipant.player_rating).label("rating"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .where(and_(GameParticipant.player_rating.is_not(None), func.date(Game.played_at) >= floor_date))
                .group_by(func.date(Game.played_at), Player.username)
                .order_by(func.date(Game.played_at), Player.username)
            ).all()

        if not rows:
            return self._demo_elo_timeseries(filters)

        return pd.DataFrame(
            [
                {
                    "date": row.played_date,
                    "player": row.username,
                    "rating": float(row.rating),
                }
                for row in rows
            ]
        )

    def get_recent_games_with_eval(self, filters: HistoryFilters) -> pd.DataFrame:
        """Get recent games for player with Stockfish evaluation."""
        if not self._has_real_data():
            return self._demo_recent_games_with_eval(filters)

        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id,
                    Game.played_at,
                    GameParticipant.opponent_username,
                    GameParticipant.color,
                    GameParticipant.result,
                    Game.time_control,
                    GameAnalysis.summary_cp,
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .outerjoin(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(Player.username == filters.player.lower())
                .order_by(Game.played_at.desc())
                .limit(filters.recent_limit)
            ).all()

        if not rows:
            return self._demo_recent_games_with_eval(filters)

        return pd.DataFrame(
            [
                {
                    "game_id": row.id,
                    "played_at": row.played_at,
                    "opponent": row.opponent_username,
                    "color": row.color,
                    "result": row.result,
                    "time_control": row.time_control,
                    "stockfish_cp": int(row.summary_cp or 0),
                }
                for row in rows
            ]
        )

    def get_opening_distribution(self, filters: HistoryFilters, moves_depth: int = 5) -> pd.DataFrame:
        """Get frequency distribution of openings played by player."""
        if not self._has_real_data():
            return self._demo_opening_distribution(moves_depth)

        floor_date = datetime.utcnow() - timedelta(days=filters.lookback_days)
        with get_session() as session:
            rows = session.execute(
                select(Game.opening_name, func.count().label("games"))
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .where(and_(Player.username == filters.player.lower(), Game.played_at >= floor_date))
                .group_by(Game.opening_name)
                .order_by(func.count().desc())
            ).all()

        if not rows:
            return self._demo_opening_distribution(moves_depth)

        return pd.DataFrame(
            [
                {
                    "opening": row.opening_name or "Unknown",
                    "games": int(row.games),
                    "depth": moves_depth,
                }
                for row in rows
            ]
        )

    def _demo_elo_timeseries(self, filters: HistoryFilters) -> pd.DataFrame:
        """Generate demo ELO timeseries with random variation."""
        random.seed(42)
        start = date.today() - timedelta(days=filters.lookback_days)
        rows: list[dict] = []

        for idx, name in enumerate(self._demo_players):
            rating = 1100 + idx * 120
            for day in range(filters.lookback_days + 1):
                d = start + timedelta(days=day)
                drift = random.randint(-8, 8)
                rating = max(700, rating + drift)
                rows.append({"date": d, "player": name, "rating": rating})

        return pd.DataFrame(rows)

    def _demo_recent_games_with_eval(self, filters: HistoryFilters) -> pd.DataFrame:
        """Generate demo recent games with random results and evaluations."""
        random.seed(7)
        rows: list[dict] = []
        today = datetime.now()
        opponents = ["Nora", "Kai", "Iris", "Liam", "Mina"]
        results = ["Win", "Loss", "Draw"]
        colors = ["White", "Black"]

        for i in range(filters.recent_limit):
            game_id = f"{filters.player}-{i + 1:04d}"
            rows.append(
                {
                    "game_id": game_id,
                    "played_at": today - timedelta(days=i),
                    "opponent": random.choice(opponents),
                    "color": random.choice(colors),
                    "result": random.choice(results),
                    "time_control": random.choice(["10+0", "15+10", "5+0"]),
                    "stockfish_cp": random.randint(-180, 220),
                }
            )

        return pd.DataFrame(rows)

    def _demo_opening_distribution(self, moves_depth: int) -> pd.DataFrame:
        """Generate demo opening frequency distribution."""
        openings = {
            "Italian Game": 26,
            "Queen's Gambit": 18,
            "Sicilian Defense": 22,
            "French Defense": 11,
            "London System": 15,
            "Other": 8,
        }
        return pd.DataFrame(
            [
                {"opening": name, "games": count, "depth": moves_depth}
                for name, count in openings.items()
            ]
        )
