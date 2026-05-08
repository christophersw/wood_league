"""Data service for the Welcome tab.

Provides:
  - ELO timeseries for all club players
  - Top-N recent games by combined accuracy
  - Top-N all-time games by lowest combined ACPL
  - Opening flow data for Sankey chart (3-move continuations)
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import datetime, timedelta

import chess
import chess.pgn
import pandas as pd
from sqlalchemy import and_, func, select

from app.services.opening_book import lookup_opening, matched_opening_from_pgn
from app.services.opening_labels import opening_display_label
from app.storage.database import get_session, init_db
from app.storage.models import (
    Game,
    GameAnalysis,
    GameParticipant,
    Lc0GameAnalysis,
    MoveAnalysis,
    Player,
    SystemEvent,
)

_SAN_CLEAN = re.compile(r"[+#!?]")

# Games with fewer than this many plies are excluded from all welcome queries.
_MIN_PLIES = 20  # 10 full moves (white + black)


def _sufficient_moves_subquery():
    """Return subquery of game IDs with analyzed move count >= MIN_PLIES."""
    """Return a subquery of game_ids with at least _MIN_PLIES analysed plies."""
    return (
        select(GameAnalysis.game_id)
        .join(MoveAnalysis, MoveAnalysis.analysis_id == GameAnalysis.id)
        .group_by(GameAnalysis.game_id)
        .having(func.count(MoveAnalysis.id) >= _MIN_PLIES)
    )


class WelcomeService:
    """Provides analytics data for the welcome dashboard: ELO, accuracy, best games, opening flows."""
    def __init__(self) -> None:
        """Initialize database."""
        init_db()

    # ── Club members ────────────────────────────────────────────────────────────

    def get_club_member_names(self) -> list[str]:
        """Return sorted list of all club player usernames."""
        with get_session() as session:
            rows = session.execute(
                select(Player.username).order_by(Player.username)
            ).scalars().all()
        return list(rows)

    # ── System events ────────────────────────────────────────────────────────────

    def get_last_system_event(self, event_type: str = "ingest") -> dict | None:
        """Return the last completed system event of a given type.
        
        Args:
            event_type: Type of event to query (e.g., "ingest", "stockfish", "lc0")
        
        Returns:
            Dict with keys: event_type, status, started_at, completed_at, duration_seconds, details
            or None if no event found.
        """
        with get_session() as session:
            event = session.execute(
                select(SystemEvent)
                .where(
                    SystemEvent.event_type == event_type,
                    SystemEvent.status.in_(["completed", "failed"]),
                )
                .order_by(SystemEvent.started_at.desc())
                .limit(1)
            ).scalar()
        
        if event is None:
            return None
        
        return {
            "event_type": event.event_type,
            "status": event.status,
            "started_at": event.started_at,
            "completed_at": event.completed_at,
            "duration_seconds": event.duration_seconds,
            "details": event.details,
        }

    # ── ELO timeseries ──────────────────────────────────────────────────────

    def get_all_players_elo_timeseries(self, lookback_days: int = 90) -> pd.DataFrame:
        """Return daily average ELO for every club player over the lookback window.

        Columns: date, player, rating
        """
        floor_date = datetime.utcnow().date() - timedelta(days=lookback_days)
        with get_session() as session:
            rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username,
                    func.avg(GameParticipant.player_rating).label("rating"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .where(
                    and_(
                        GameParticipant.player_rating.is_not(None),
                        func.date(Game.played_at) >= floor_date,
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
                .order_by(func.date(Game.played_at), Player.username)
            ).all()

        if not rows:
            return pd.DataFrame(columns=["date", "player", "rating"])

        df = pd.DataFrame(
            [
                {
                    "date": row.played_date,
                    "player": row.username,
                    "rating": float(row.rating),
                }
                for row in rows
            ]
        )
        df["date"] = pd.to_datetime(df["date"])
        return df

    # ── Player accuracy timeseries ──────────────────────────────────────────

    def get_player_accuracy_timeseries(self, lookback_days: int = 90) -> pd.DataFrame:
        """Return daily average accuracy for club players over the lookback window.

        Only players tracked in the Player table (i.e. club members) are included.
        Each player appears once per day, averaged across all their games that day.

        Columns: date, player, accuracy
        """
        floor_date = datetime.utcnow() - timedelta(days=lookback_days)
        with get_session() as session:
            # White-side rows — club player played as white
            white_rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username.label("player"),
                    func.avg(GameAnalysis.white_accuracy).label("accuracy"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        func.lower(GameParticipant.color) == "white",
                        GameAnalysis.white_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
            ).all()

            # Black-side rows — club player played as black
            black_rows = session.execute(
                select(
                    func.date(Game.played_at).label("played_date"),
                    Player.username.label("player"),
                    func.avg(GameAnalysis.black_accuracy).label("accuracy"),
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        func.lower(GameParticipant.color) == "black",
                        GameAnalysis.black_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .group_by(func.date(Game.played_at), Player.username)
            ).all()

        if not white_rows and not black_rows:
            return pd.DataFrame(columns=["date", "player", "accuracy"])

        records = [
            {"date": r.played_date, "player": r.player, "accuracy": float(r.accuracy)}
            for r in white_rows + black_rows
        ]
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"])
        # Average across both colors when a player played multiple games on one day
        df = (
            df.groupby(["date", "player"], as_index=False)["accuracy"]
            .mean()
            .sort_values(["date", "player"])
        )
        return df

    # ── Best recent games (by accuracy) ─────────────────────────────────────

    def get_best_recent_games_by_accuracy(
        self,
        limit: int = 10,
        lookback_days: int = 30,
    ) -> pd.DataFrame:
        """Top N games played within *lookback_days*, ranked by combined accuracy.

        Columns: game_id, played_at, white, black, avg_accuracy,
                 white_accuracy, black_accuracy,
                 wdl_win, wdl_draw, wdl_loss
        """
        floor_date = datetime.utcnow() - timedelta(days=lookback_days)
        avg_acc = (GameAnalysis.white_accuracy + GameAnalysis.black_accuracy) / 2
        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id,
                    Game.played_at,
                    Game.white_username,
                    Game.black_username,
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                    Lc0GameAnalysis.white_win_prob,
                    Lc0GameAnalysis.white_draw_prob,
                    Lc0GameAnalysis.white_loss_prob,
                )
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .outerjoin(Lc0GameAnalysis, Lc0GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        GameAnalysis.white_accuracy.is_not(None),
                        GameAnalysis.black_accuracy.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .order_by(avg_acc.desc())
                .limit(limit)
            ).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(
            [
                {
                    "game_id": row.id,
                    "played_at": row.played_at,
                    "white": row.white_username or "?",
                    "black": row.black_username or "?",
                    "avg_accuracy": (row.white_accuracy + row.black_accuracy) / 2,
                    "white_accuracy": row.white_accuracy,
                    "black_accuracy": row.black_accuracy,
                    "wdl_win": row.white_win_prob,
                    "wdl_draw": row.white_draw_prob,
                    "wdl_loss": row.white_loss_prob,
                }
                for row in rows
            ]
        )

    # ── Best all-time games (by ACPL) ────────────────────────────────────────

    def get_best_all_time_games_by_acpl(self, limit: int = 10) -> pd.DataFrame:
        """Top N all-time games ranked by lowest combined ACPL.

        Columns: game_id, played_at, white, black, avg_acpl,
                 white_acpl, black_acpl, white_accuracy, black_accuracy,
                 wdl_win, wdl_draw, wdl_loss
        """
        avg_acpl = (GameAnalysis.white_acpl + GameAnalysis.black_acpl) / 2
        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id,
                    Game.played_at,
                    Game.white_username,
                    Game.black_username,
                    GameAnalysis.white_acpl,
                    GameAnalysis.black_acpl,
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                    Lc0GameAnalysis.white_win_prob,
                    Lc0GameAnalysis.white_draw_prob,
                    Lc0GameAnalysis.white_loss_prob,
                )
                .join(GameAnalysis, GameAnalysis.game_id == Game.id)
                .outerjoin(Lc0GameAnalysis, Lc0GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        GameAnalysis.white_acpl.is_not(None),
                        GameAnalysis.black_acpl.is_not(None),
                        Game.id.in_(_sufficient_moves_subquery()),
                    )
                )
                .order_by(avg_acpl.asc())
                .limit(limit)
            ).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(
            [
                {
                    "game_id": row.id,
                    "played_at": row.played_at,
                    "white": row.white_username or "?",
                    "black": row.black_username or "?",
                    "avg_acpl": (row.white_acpl + row.black_acpl) / 2,
                    "white_acpl": row.white_acpl,
                    "black_acpl": row.black_acpl,
                    "white_accuracy": row.white_accuracy,
                    "black_accuracy": row.black_accuracy,
                    "wdl_win": row.white_win_prob,
                    "wdl_draw": row.white_draw_prob,
                    "wdl_loss": row.white_loss_prob,
                }
                for row in rows
            ]
        )

    # ── Most recent games ────────────────────────────────────────────────────

    def get_most_recent_games(self, limit: int = 10) -> pd.DataFrame:
        """Top N most recently played games with opening and accuracy info.

        Columns: game_id, played_at, white, black, opening_name, opening_id,
                 avg_accuracy, white_accuracy, black_accuracy
        """
        with get_session() as session:
            rows = session.execute(
                select(
                    Game.id.label("game_id"),
                    Game.slug,
                    Game.played_at,
                    Game.white_username,
                    Game.black_username,
                    Game.eco_code,
                    Game.opening_name,
                    Game.lichess_opening,
                    Game.pgn,
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                )
                .outerjoin(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    Game.id.in_(_sufficient_moves_subquery())
                )
                .order_by(Game.played_at.desc())
                .limit(limit)
            ).all()

        if not rows:
            return pd.DataFrame()

        opening_entry_by_game_id = {
            row.game_id: matched_opening_from_pgn(row.pgn or "", max_ply=20)
            for row in rows
        }

        return pd.DataFrame(
            [
                {
                    "game_id": row.game_id,
                    "slug": row.slug,
                    "played_at": row.played_at,
                    "white": row.white_username or "?",
                    "black": row.black_username or "?",
                    "opening_name": opening_display_label(
                        row.eco_code,
                        row.lichess_opening,
                        row.opening_name,
                        row.pgn,
                    ),
                    "opening_id": (
                        opening_entry_by_game_id[row.game_id][0]
                        if opening_entry_by_game_id[row.game_id] is not None
                        else None
                    ),
                    "white_accuracy": row.white_accuracy,
                    "black_accuracy": row.black_accuracy,
                    "avg_accuracy": (row.white_accuracy + row.black_accuracy) / 2
                    if row.white_accuracy is not None and row.black_accuracy is not None
                    else None,
                }
                for row in rows
            ]
        )

    # ── Opening flow (Sankey) ────────────────────────────────────────────────

    def get_opening_flow(
        self,
        lookback_days: int = 90,
        players: list[str] | None = None,
        min_games: int = 2,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return data for a 3-level opening continuation Sankey chart.

        Builds 3 Sankey levels by looking up opening book names at plies 2, 4,
        and 6 (after white's 1st, 2nd, and 3rd moves):
          Level 1: opening name after move 1 pair  (e.g. "King's Pawn Game")
          Level 2: opening name after move 2 pair  (e.g. "King's Knight Opening")
          Level 3: opening name after move 3 pair  (e.g. "Italian Game")

        Returns (edges_df, node_stats_df):

        edges_df columns: source, target, games
        node_stats_df columns: node, games, wins, draws, losses,
            win_pct, draw_pct, loss_pct,
            avg_white_accuracy, avg_black_accuracy,
            players (dict: username → game_count)
        """
        floor_date = datetime.utcnow() - timedelta(days=lookback_days)

        with get_session() as session:
            stmt = (
                select(
                    Game.id.label("game_id"),
                    Game.pgn,
                    Game.white_username,
                    Game.black_username,
                    GameParticipant.color,
                    GameParticipant.result,
                    Player.username.label("club_player"),
                    GameAnalysis.white_accuracy,
                    GameAnalysis.black_accuracy,
                )
                .join(GameParticipant, GameParticipant.game_id == Game.id)
                .join(Player, Player.id == GameParticipant.player_id)
                .outerjoin(GameAnalysis, GameAnalysis.game_id == Game.id)
                .where(
                    and_(
                        Game.played_at >= floor_date,
                        Game.pgn.is_not(None),
                        Game.pgn != "",
                    )
                )
                .order_by(Game.played_at.desc())
            )
            if players:
                stmt = stmt.where(
                    func.lower(Player.username).in_([p.lower() for p in players])
                )
            rows = session.execute(stmt).all()

        if not rows:
            return pd.DataFrame(), pd.DataFrame()

        # One record per (game_id, club_player) — games with two club players
        # appear twice so each player's W/L/D perspective is counted.
        seen: set[tuple[int, str]] = set()
        records = []
        for row in rows:
            key = (row.game_id, row.club_player)
            if key in seen:
                continue
            seen.add(key)
            records.append(row)

        edge_counts: dict[tuple[str, str], int] = defaultdict(int)
        node_data: dict[str, dict] = {}

        for row in records:
            path = self._opening_name_path(row.pgn)
            if not path:
                continue

            result = row.result
            w_acc = row.white_accuracy
            b_acc = row.black_accuracy
            player = row.club_player

            for i in range(len(path) - 1):
                edge_counts[(path[i], path[i + 1])] += 1

            for node_label in path:
                if node_label not in node_data:
                    node_data[node_label] = {
                        "games": 0, "wins": 0, "draws": 0, "losses": 0,
                        "white_acc_sum": 0.0, "white_acc_n": 0,
                        "black_acc_sum": 0.0, "black_acc_n": 0,
                        "players": defaultdict(int),
                    }
                nd = node_data[node_label]
                nd["games"] += 1
                if result == "Win":
                    nd["wins"] += 1
                elif result == "Draw":
                    nd["draws"] += 1
                else:
                    nd["losses"] += 1
                if w_acc is not None:
                    nd["white_acc_sum"] += w_acc
                    nd["white_acc_n"] += 1
                if b_acc is not None:
                    nd["black_acc_sum"] += b_acc
                    nd["black_acc_n"] += 1
                nd["players"][player] += 1

        if not edge_counts:
            return pd.DataFrame(), pd.DataFrame()

        edges_df = pd.DataFrame(
            [{"source": s, "target": t, "games": c} for (s, t), c in edge_counts.items()]
        )
        edges_df = edges_df[edges_df["games"] >= min_games].reset_index(drop=True)

        node_rows = []
        for label, nd in node_data.items():
            g = nd["games"]
            node_rows.append({
                "node": label,
                "games": g,
                "wins": nd["wins"],
                "draws": nd["draws"],
                "losses": nd["losses"],
                "win_pct": round(nd["wins"] / g * 100, 1) if g else 0.0,
                "draw_pct": round(nd["draws"] / g * 100, 1) if g else 0.0,
                "loss_pct": round(nd["losses"] / g * 100, 1) if g else 0.0,
                "avg_white_accuracy": (
                    round(nd["white_acc_sum"] / nd["white_acc_n"], 1)
                    if nd["white_acc_n"] else None
                ),
                "avg_black_accuracy": (
                    round(nd["black_acc_sum"] / nd["black_acc_n"], 1)
                    if nd["black_acc_n"] else None
                ),
                "players": dict(nd["players"]),
            })
        node_stats_df = pd.DataFrame(node_rows)

        return edges_df, node_stats_df

    @staticmethod
    def _opening_name_path(pgn_text: str) -> list[str]:
        """Return a 3-node opening name path by querying the opening book
        at plies 2, 4, and 6 (after each of the first 3 full move pairs).

        Returns [] if the game has fewer than 2 half-moves.
        Consecutive identical names are deduplicated to avoid self-loops.
        """
        try:
            game = chess.pgn.read_game(io.StringIO(pgn_text))
        except Exception:
            return []
        if game is None:
            return []

        board = game.board()
        path_names: list[str] = []
        node = game
        ply = 0

        while ply < 6:
            if not node.variations:
                break
            node = node.variations[0]
            board.push(node.move)
            ply += 1

            # Sample at plies 2, 4, 6 (after each full move pair)
            if ply % 2 == 0:
                result = lookup_opening(board)
                if result:
                    _, name = result
                    # Strip the opening family prefix (everything before ":")
                    # to get a compact variation label for deeper levels.
                    if ply > 2 and ":" in name:
                        name = name.split(":", 1)[1].strip()
                    # Trim for Sankey readability
                    if len(name) > 36:
                        name = name[:35] + "…"
                    path_names.append(name)
                else:
                    # No match at this ply — carry forward last known name
                    if path_names:
                        path_names.append(path_names[-1])

        if not path_names:
            return []

        # Deduplicate consecutive identical names (avoids self-loops in Sankey)
        deduped: list[str] = [path_names[0]]
        for name in path_names[1:]:
            if name != deduped[-1]:
                deduped.append(name)

        return deduped
