"""Views for displaying opening repertoire analysis and statistics."""

from __future__ import annotations

import json

import chess
import chess.svg
import pandas as pd
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from players.models import Player

from . import services
from .charts import opening_frequency_trend, opening_player_accuracy_bar, opening_share_pie

_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}

_TIMEFRAMES = {
    "30": 30,
    "90": 90,
    "180": 180,
    "365": 365,
}
_DEFAULT_DAYS = 90


def _parse_filter_params(request: HttpRequest) -> tuple[int | None, list[str] | None]:
    """Extract and validate 'days' and 'players' query parameters."""
    days_raw = request.GET.get("days", "")
    if days_raw == "all":
        days = None
    else:
        days = _TIMEFRAMES.get(days_raw, _DEFAULT_DAYS)
    raw_players = request.GET.get("players", "").strip()
    players = [p.strip() for p in raw_players.split(",") if p.strip()] or None
    return days, players


def _scope_label(days: int | None, players: list[str] | None, all_members: list[str]) -> str:
    """Build human-readable scope label for filters (timeframe and players)."""
    if days is None:
        tf = "All time"
    else:
        tf = {30: "Last 30 days", 90: "Last 90 days", 180: "Last 6 months", 365: "Last year"}.get(days, f"Last {days} days")

    if not players or set(players) == set(all_members):
        pl = "All members"
    elif len(players) <= 4:
        pl = ", ".join(players)
    else:
        pl = f"{len(players)} selected players"

    return f"{tf} · Players: {pl}"


def _build_board_svg(fen: str) -> str:
    """Render board position from FEN as SVG with styled colors and coordinates."""
    board = chess.Board(fen)
    return chess.svg.board(board, size=340, colors=_BOARD_COLORS, coordinates=True)


@login_required
@require_GET
def detail(request: HttpRequest, opening_id: int) -> HttpResponse:
    """Display full opening detail page with board, lineage tree, and stats tabs."""
    opening = services.get_opening(opening_id)
    if opening is None:
        return render(request, "openings/not_found.html", {"opening_id": opening_id}, status=404)

    all_members = list(Player.objects.order_by("username").values_list("username", flat=True))

    board_svg = _build_board_svg(opening["final_fen"])

    tree_ctx = services.opening_tree_context(
        opening,
        lookback_days=_DEFAULT_DAYS,
        players=None,
        max_children=9,
    )
    tree_svg, tree_height = services.opening_tree_svg(tree_ctx, opening["epd"])

    return render(request, "openings/detail.html", {
        "opening": opening,
        "board_svg": board_svg,
        "tree_svg": tree_svg,
        "tree_height": tree_height,
        "tree_selected_games": tree_ctx.get("selected_games", 0),
        "tree_total_scoped": tree_ctx.get("total_scoped_games", 0),
        "all_members": all_members,
        "all_members_json": json.dumps(all_members),
        "timeframe_options": [
            ("30", "Last 30 days"),
            ("90", "Last 90 days"),
            ("180", "Last 6 months"),
            ("365", "Last year"),
            ("all", "All time"),
        ],
        "default_days": str(_DEFAULT_DAYS),
    })


@login_required
@require_GET
def stats_partial(request: HttpRequest, opening_id: int) -> HttpResponse:
    """Return HTMX partial with charts and tables for opening stats based on filters."""
    opening = services.get_opening(opening_id)
    if opening is None:
        return HttpResponse("<p class='font-mono text-sm text-peat'>Opening not found.</p>", status=404)

    all_members = list(Player.objects.order_by("username").values_list("username", flat=True))

    days, players = _parse_filter_params(request)
    active_players = players or all_members
    scope = _scope_label(days, active_players, all_members)

    games_df = services.get_games(opening, lookback_days=days, players=active_players)
    stats_df = services.player_stats(games_df)
    freq_df = services.frequency_over_time(games_df)
    share_df = services.opening_share(opening, games_df, lookback_days=days, players=active_players)

    share_json = opening_share_pie(share_df, opening["name"], scope_label=scope).to_json() if not share_df.empty else "{}"
    acc_json = opening_player_accuracy_bar(stats_df, opening["name"], scope_label=scope).to_json() if not stats_df.empty else "{}"
    freq_json = opening_frequency_trend(freq_df, opening["name"], scope_label=scope).to_json() if not freq_df.empty else "{}"

    # Build game table rows
    game_rows = []
    if not games_df.empty:
        tbl = games_df.drop_duplicates(subset=["game_id"], keep="first").sort_values("played_at", ascending=False)
        for _, row in tbl.iterrows():
            color = row["color"]
            opponent = row["black_username"] if color == "white" else row["white_username"]
            acc = row["white_accuracy"] if color == "white" else row["black_accuracy"]
            acpl = row["white_acpl"] if color == "white" else row["black_acpl"]
            game_rows.append({
                "date": row["played_at"].strftime("%d %b %Y") if hasattr(row["played_at"], "strftime") else str(row["played_at"])[:10],
                "club_player": row["club_player"],
                "color_sym": "♙" if color == "white" else "♟",
                "opponent": str(opponent),
                "result": row["result"],
                "accuracy": f"{acc:.1f}%" if pd.notna(acc) else "—",
                "acpl": f"{acpl:.1f}" if pd.notna(acpl) else "—",
                "slug": row.get("slug", ""),
                "game_id": row["game_id"],
            })

    stats_rows = []
    if not stats_df.empty:
        for _, row in stats_df.iterrows():
            stats_rows.append({
                "player": row["player"],
                "games": int(row["games"]),
                "wins": int(row["wins"]),
                "draws": int(row["draws"]),
                "losses": int(row["losses"]),
                "win_pct": float(row["win_pct"]),
                "draw_pct": float(row["draw_pct"]),
                "loss_pct": float(row["loss_pct"]),
                "avg_accuracy": row.get("avg_accuracy"),
                "avg_acpl": row.get("avg_acpl"),
                "as_white": int(row["as_white"]),
                "as_black": int(row["as_black"]),
            })

    return render(request, "openings/_stats_partial.html", {
        "opening": opening,
        "scope_label": scope,
        "total_games": games_df["game_id"].nunique() if not games_df.empty else 0,
        "stats_rows": stats_rows,
        "game_rows": game_rows,
        "share_chart_json": share_json,
        "acc_chart_json": acc_json,
        "freq_chart_json": freq_json,
        "has_games": not games_df.empty,
    })
