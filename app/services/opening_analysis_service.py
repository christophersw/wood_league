"""Opening analysis service for statistical analysis of opening repertoires and frequency.

Computes opening metrics, win rates, timelines, family distributions, and variation flows
from game history with configurable player and color filters.
"""
from __future__ import annotations

from dataclasses import dataclass
import io

import chess.pgn
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.services.opening_labels import opening_display_label
from app.storage.database import get_session, init_db
from app.storage.models import Game, GameAnalysis, GameParticipant, MoveAnalysis, Player


@dataclass
class OpeningMetricsFilters:
    """Filter parameters for opening analysis: player and color."""
    player: str | None = None
    color: str | None = None


class OpeningAnalysisService:
    """Analyzes opening repertoire statistics and trends from game history."""
    def __init__(self) -> None:
        """Initialize with config settings and database."""
        self._settings = get_settings()
        init_db()

    def list_players(self) -> list[str]:
        """Return all players in database."""
        with get_session() as session:
            rows = session.scalars(select(Player.username).order_by(Player.username)).all()
        return list(rows)

    def club_recent_games(self, limit: int | None = None) -> pd.DataFrame:
        """Get recent games for entire club with opening data."""
        return self._recent_games(limit=limit)

    def player_recent_games(self, player: str, limit: int | None = None) -> pd.DataFrame:
        """Get recent games for specific player with opening data."""
        if not player:
            return pd.DataFrame()
        return self._recent_games(limit=limit, player=player)

    def opening_metrics_table(self, df: pd.DataFrame, filters: OpeningMetricsFilters | None = None) -> pd.DataFrame:
        """Aggregate opening statistics: wins, losses, draws, averages by opening."""
        if df.empty:
            return pd.DataFrame()

        working = df.copy()
        filters = filters or OpeningMetricsFilters()

        if filters.player:
            working = working[working["player"] == filters.player.lower()]
        if filters.color:
            working = working[working["color"] == filters.color]

        if working.empty:
            return pd.DataFrame()

        grouped = working.groupby("opening_label", as_index=False).agg(
            games=("game_id", "count"),
            wins=("result", lambda s: int((s == "Win").sum())),
            draws=("result", lambda s: int((s == "Draw").sum())),
            losses=("result", lambda s: int((s == "Loss").sum())),
            avg_game_length=("game_length_plies", "mean"),
            avg_move10_cp=("move10_cp", "mean"),
        )

        grouped["win_pct"] = (grouped["wins"] / grouped["games"] * 100).round(1)
        grouped["draw_pct"] = (grouped["draws"] / grouped["games"] * 100).round(1)
        grouped["loss_pct"] = (grouped["losses"] / grouped["games"] * 100).round(1)
        grouped["avg_game_length"] = grouped["avg_game_length"].round(1)
        grouped["avg_move10_cp"] = grouped["avg_move10_cp"].round(1)

        return grouped.sort_values(["games", "win_pct"], ascending=[False, False]).reset_index(drop=True)

    def opening_timeline(self, df: pd.DataFrame, top_n: int = 20, bucket: str | None = None) -> pd.DataFrame:
        """Create timeline of top openings bucketed by day, week, or month."""
        if df.empty:
            return pd.DataFrame()

        working = df.copy()
        top_openings = (
            working.groupby("opening_label")["game_id"]
            .count()
            .sort_values(ascending=False)
            .head(top_n)
            .index.tolist()
        )
        filtered = working[working["opening_label"].isin(top_openings)].copy()
        if filtered.empty:
            return pd.DataFrame()

        bucket = (bucket or "").upper().strip() or self._default_timeline_bucket(filtered)
        if bucket not in {"D", "W", "M"}:
            bucket = "W"

        filtered["time_bucket"] = pd.to_datetime(filtered["played_at"]).dt.to_period(bucket).dt.start_time
        timeline = (
            filtered.groupby(["opening_label", "time_bucket"], as_index=False)["game_id"]
            .count()
            .rename(columns={"game_id": "games"})
            .sort_values(["opening_label", "time_bucket"])
        )
        timeline["bucket_label"] = {"D": "Day", "W": "Week", "M": "Month"}[bucket]
        return timeline

    def opening_family_fingerprint(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute opening family distribution: King's Pawn, Queen's Pawn, etc."""
        if df.empty:
            return pd.DataFrame()

        families = ["King's Pawn", "Queen's Pawn", "Flank", "Indian Defense", "Other"]
        counts = df.groupby("opening_family")["game_id"].count().to_dict()
        total = max(len(df), 1)

        rows = []
        for family in families:
            value = int(counts.get(family, 0))
            rows.append({"family": family, "share_pct": round(value / total * 100, 1), "games": value})
        return pd.DataFrame(rows)

    def opening_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create opening family-to-variation flow for Sankey visualization."""
        if df.empty:
            return pd.DataFrame()

        working = df.copy()
        working["variation"] = working["opening_label"].apply(self._variation_name)

        flow = (
            working.groupby(["opening_family", "variation"], as_index=False)["game_id"]
            .count()
            .rename(columns={"game_id": "games", "opening_family": "source", "variation": "target"})
            .sort_values("games", ascending=False)
        )
        return flow.head(40)

    def _recent_games(self, limit: int | None = None, player: str | None = None) -> pd.DataFrame:
        """Fetch recent games with opening data; cache-friendly via ELO snapshot at move 10."""
        effective_limit = limit
        if effective_limit is None:
            configured_cap = int(self._settings.opening_analysis_max_rows)
            effective_limit = configured_cap if configured_cap > 0 else None

        move10_alias = aliased(MoveAnalysis)
        with get_session() as session:
            stmt = (
                select(
                    Game.id.label("game_id"),
                    Game.played_at,
                    Player.username.label("player"),
                    GameParticipant.color,
                    GameParticipant.result,
                    Game.eco_code,
                    Game.opening_name,
                    Game.lichess_opening,
                    Game.pgn,
                    GameAnalysis.summary_cp,
                    move10_alias.cp_eval.label("move10_cp"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .outerjoin(GameAnalysis, GameAnalysis.game_id == Game.id)
                .outerjoin(
                    move10_alias,
                    (move10_alias.analysis_id == GameAnalysis.id) & (move10_alias.ply == 20),
                )
                .order_by(Game.played_at.desc())
            )

            if effective_limit is not None and effective_limit > 0:
                stmt = stmt.limit(effective_limit)

            if player:
                stmt = stmt.where(func.lower(Player.username) == player.lower())

            rows = session.execute(stmt).all()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "game_id": row.game_id,
                    "played_at": row.played_at,
                    "player": row.player,
                    "color": row.color,
                    "result": row.result,
                    "eco_code": row.eco_code or "",
                    "opening_name": row.opening_name or "",
                    "lichess_opening": row.lichess_opening or "",
                    "opening_label": self._opening_label(row.eco_code, row.lichess_opening, row.opening_name, row.pgn),
                    "opening_family": self._opening_family(row.eco_code, row.lichess_opening, row.opening_name, row.pgn),
                    "pgn": row.pgn or "",
                    "summary_cp": row.summary_cp,
                    "move10_cp": row.move10_cp if row.move10_cp is not None else row.summary_cp,
                }
                for row in rows
            ]
        )

        df["game_length_plies"] = df["pgn"].apply(self._game_length_plies)
        df["played_date"] = pd.to_datetime(df["played_at"]).dt.date
        return df

    @staticmethod
    def _opening_label(
        eco_code: str | None,
        lichess_opening: str | None,
        opening_name: str | None,
        pgn_text: str | None,
    ) -> str:
        """Get display-friendly opening label from ECO and name fields."""
        return opening_display_label(eco_code, lichess_opening, opening_name, pgn_text)

    @staticmethod
    def _opening_family(
        eco_code: str | None,
        lichess_opening: str | None,
        opening_name: str | None,
        pgn_text: str | None,
    ) -> str:
        """Classify opening into family: King's Pawn, Queen's Pawn, Indian Defense, Flank, Other."""
        eco = (eco_code or "").strip().upper()
        name = opening_display_label(eco_code, lichess_opening, opening_name, pgn_text).lower()

        if eco.startswith(("B", "C")):
            return "King's Pawn"
        if eco.startswith("D"):
            return "Queen's Pawn"
        if eco.startswith("E"):
            return "Indian Defense"
        if eco.startswith("A"):
            return "Flank"

        if any(k in name for k in ["sicilian", "french", "caro-kann", "italian", "ruy", "scotch"]):
            return "King's Pawn"
        if any(k in name for k in ["queen", "london", "slav", "qgd", "nimzo"]):
            return "Queen's Pawn"
        if any(k in name for k in ["indian", "grunfeld", "nimzo", "benoni", "kings indian"]):
            return "Indian Defense"
        if any(k in name for k in ["english", "reti", "bird", "orangutan", "flank"]):
            return "Flank"
        return "Other"

    @staticmethod
    def _variation_name(label: str) -> str:
        """Extract variation name from full opening label (suffix after colon)."""
        text = str(label or "").strip()
        if not text:
            return "Unknown"
        if ":" in text:
            return text.split(":", 1)[1].strip() or text
        parts = text.split()
        if len(parts) <= 2:
            return text
        return " ".join(parts[2:])

    @staticmethod
    def _game_length_plies(pgn_text: str) -> int | None:
        """Parse PGN to count total plies (moves from both sides)."""
        pgn = str(pgn_text or "").strip()
        if not pgn:
            return None

        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None:
            return None
        return sum(1 for _ in game.mainline_moves())

    @staticmethod
    def _default_timeline_bucket(df: pd.DataFrame) -> str:
        """Infer time bucketing (day/week/month) from date span."""
        played = pd.to_datetime(df["played_at"], errors="coerce")
        if played.empty:
            return "W"

        min_dt = played.min()
        max_dt = played.max()
        if pd.isna(min_dt) or pd.isna(max_dt):
            return "W"

        span_days = max((max_dt - min_dt).days, 0)
        if span_days <= 45:
            return "D"
        if span_days <= 240:
            return "W"
        return "M"
