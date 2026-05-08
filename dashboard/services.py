"""Django ORM port of WelcomeService — dashboard data queries."""

from __future__ import annotations

import io
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import chess
import chess.pgn
import pandas as pd
from django.db.models import Avg, Count, F, Q, Subquery, OuterRef
from django.db.models.functions import TruncDate

from analysis.models import GameAnalysis, MoveAnalysis, Lc0GameAnalysis
from games.models import Game, GameParticipant
from ingest.models import SystemEvent
from openings.models import OpeningBook
from players.models import Player

_MIN_PLIES = 20
_SAN_CLEAN = re.compile(r"[+#!?]")


def _analyzed_game_ids():
    """Subquery: game IDs that have at least _MIN_PLIES analysed move records."""
    enough = (
        MoveAnalysis.objects
        .values("analysis__game_id")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=_MIN_PLIES)
        .values("analysis__game_id")
    )
    return enough


def get_club_member_names() -> list[str]:
    """Return a sorted list of all player usernames in the club."""
    return list(Player.objects.order_by("username").values_list("username", flat=True))


def get_last_system_event(event_type: str = "ingest") -> dict | None:
    """Get the most recent system event of the given type (ingest or analysis)."""
    event = (
        SystemEvent.objects
        .filter(event_type=event_type, status__in=["completed", "failed"])
        .order_by("-started_at")
        .first()
    )
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


def get_most_recent_games(limit: int = 10) -> list[dict]:
    """Fetch recent games with analysis results, sorted by date."""
    analyzed_ids = _analyzed_game_ids()
    games = (
        Game.objects
        .filter(id__in=Subquery(analyzed_ids))
        .select_related("analysis")
        .order_by("-played_at")[:limit]
    )
    rows = []
    for g in games:
        analysis = getattr(g, "analysis", None)
        avg_acc = None
        if analysis and analysis.white_accuracy is not None and analysis.black_accuracy is not None:
            avg_acc = (analysis.white_accuracy + analysis.black_accuracy) / 2
        rows.append({
            "game_id": g.id,
            "slug": g.slug,
            "played_at": g.played_at,
            "white": g.white_username or "?",
            "black": g.black_username or "?",
            "opening_name": g.lichess_opening or g.opening_name or "Unknown",
            "eco_code": g.eco_code,
            "white_accuracy": analysis.white_accuracy if analysis else None,
            "black_accuracy": analysis.black_accuracy if analysis else None,
            "avg_accuracy": avg_acc,
        })
    return rows


def get_player_accuracy_timeseries(
    lookback_days: int = 90,
    players: list[str] | None = None,
) -> pd.DataFrame:
    """Return accuracy timeseries for players over the lookback period."""
    floor_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    analyzed_ids = _analyzed_game_ids()

    qs = (
        GameParticipant.objects
        .filter(
            game__played_at__gte=floor_date,
            game_id__in=Subquery(analyzed_ids),
        )
        .select_related("game__analysis", "player")
    )
    if players:
        qs = qs.filter(player__username__in=players)

    records = []
    for gp in qs.iterator():
        analysis = getattr(gp.game, "analysis", None)
        if analysis is None:
            continue
        if gp.color.lower() == "white" and analysis.white_accuracy is not None:
            records.append({
                "date": gp.game.played_at.date(),
                "player": gp.player.username,
                "accuracy": analysis.white_accuracy,
            })
        elif gp.color.lower() == "black" and analysis.black_accuracy is not None:
            records.append({
                "date": gp.game.played_at.date(),
                "player": gp.player.username,
                "accuracy": analysis.black_accuracy,
            })

    if not records:
        return pd.DataFrame(columns=["date", "player", "accuracy"])

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.groupby(["date", "player"], as_index=False)["accuracy"]
        .mean()
        .sort_values(["date", "player"])
    )
    return df


def get_all_players_elo_timeseries(
    lookback_days: int = 90,
    players: list[str] | None = None,
) -> pd.DataFrame:
    """Return ELO rating timeseries for players over the lookback period."""
    floor_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    qs = (
        GameParticipant.objects
        .filter(
            game__played_at__gte=floor_date,
            player_rating__isnull=False,
        )
        .select_related("game", "player")
    )
    if players:
        qs = qs.filter(player__username__in=players)

    records = [
        {
            "date": gp.game.played_at.date(),
            "player": gp.player.username,
            "rating": gp.player_rating,
        }
        for gp in qs.iterator()
    ]

    if not records:
        return pd.DataFrame(columns=["date", "player", "rating"])

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df = (
        df.groupby(["date", "player"], as_index=False)["rating"]
        .mean()
        .sort_values(["date", "player"])
    )
    return df


def get_best_recent_games_by_accuracy(
    limit: int = 10,
    lookback_days: int = 30,
) -> list[dict]:
    """Get highest-accuracy games from the recent lookback period."""
    floor_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    analyzed_ids = _analyzed_game_ids()

    games = (
        Game.objects
        .filter(
            played_at__gte=floor_date,
            id__in=Subquery(analyzed_ids),
            analysis__white_accuracy__isnull=False,
            analysis__black_accuracy__isnull=False,
        )
        .select_related("analysis", "lc0_analysis")
        .annotate(
            avg_acc=F("analysis__white_accuracy") + F("analysis__black_accuracy")
        )
        .order_by("-avg_acc")[:limit]
    )

    return [
        {
            "game_id": g.id,
            "slug": g.slug,
            "played_at": g.played_at,
            "white": g.white_username or "?",
            "black": g.black_username or "?",
            "avg_accuracy": (g.analysis.white_accuracy + g.analysis.black_accuracy) / 2,
            "white_accuracy": g.analysis.white_accuracy,
            "black_accuracy": g.analysis.black_accuracy,
            "wdl_win": g.lc0_analysis.white_win_prob if hasattr(g, "lc0_analysis") and g.lc0_analysis else None,
            "wdl_draw": g.lc0_analysis.white_draw_prob if hasattr(g, "lc0_analysis") and g.lc0_analysis else None,
            "wdl_loss": g.lc0_analysis.white_loss_prob if hasattr(g, "lc0_analysis") and g.lc0_analysis else None,
        }
        for g in games
    ]


def get_best_all_time_games_by_acpl(limit: int = 10) -> list[dict]:
    """Get lowest average centipawn loss (best) games across all time."""
    analyzed_ids = _analyzed_game_ids()

    games = (
        Game.objects
        .filter(
            id__in=Subquery(analyzed_ids),
            analysis__white_acpl__isnull=False,
            analysis__black_acpl__isnull=False,
        )
        .select_related("analysis", "lc0_analysis")
        .annotate(
            avg_acpl=F("analysis__white_acpl") + F("analysis__black_acpl")
        )
        .order_by("avg_acpl")[:limit]
    )

    return [
        {
            "game_id": g.id,
            "slug": g.slug,
            "played_at": g.played_at,
            "white": g.white_username or "?",
            "black": g.black_username or "?",
            "avg_acpl": (g.analysis.white_acpl + g.analysis.black_acpl) / 2,
            "white_acpl": g.analysis.white_acpl,
            "black_acpl": g.analysis.black_acpl,
            "white_accuracy": g.analysis.white_accuracy,
            "black_accuracy": g.analysis.black_accuracy,
            "wdl_win": g.lc0_analysis.white_win_prob if hasattr(g, "lc0_analysis") and g.lc0_analysis else None,
        }
        for g in games
    ]


def get_opening_flow(
    lookback_days: int = 90,
    players: list[str] | None = None,
    min_games: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return opening move flow as edge and node statistics dataframes."""
    floor_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    qs = (
        GameParticipant.objects
        .filter(
            game__played_at__gte=floor_date,
            game__pgn__isnull=False,
        )
        .exclude(game__pgn="")
        .select_related("game__analysis", "player")
    )
    if players:
        qs = qs.filter(player__username__in=players)

    seen: set[tuple[str, str]] = set()
    records = []
    for gp in qs.iterator():
        key = (gp.game_id, gp.player.username)
        if key in seen:
            continue
        seen.add(key)
        records.append(gp)

    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    node_data: dict[str, dict] = {}

    for gp in records:
        path = _opening_name_path(gp.game.pgn)
        if not path:
            continue
        analysis = getattr(gp.game, "analysis", None)
        w_acc = analysis.white_accuracy if analysis else None
        b_acc = analysis.black_accuracy if analysis else None
        player = gp.player.username

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
            if gp.result == "Win":
                nd["wins"] += 1
            elif gp.result == "Draw":
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


def _opening_name_path(pgn_text: str) -> list[str]:
    """Return a 3-node opening name path sampled at plies 2, 4, 6."""
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

        if ply % 2 == 0:
            epd = board.epd()
            entry = OpeningBook.objects.filter(epd__startswith=epd.split(" ")[0]).first()
            if entry:
                name = entry.name
                if ply > 2 and ":" in name:
                    name = name.split(":", 1)[1].strip()
                if len(name) > 36:
                    name = name[:35] + "…"
                path_names.append(name)
            elif path_names:
                path_names.append(path_names[-1])

    if not path_names:
        return []

    deduped: list[str] = [path_names[0]]
    for name in path_names[1:]:
        if name != deduped[-1]:
            deduped.append(name)
    return deduped
