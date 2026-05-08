"""Dashboard views and HTMX partial endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from .charts import player_accuracy_chart, player_elo_chart, welcome_opening_sankey
from . import services

_TIMEFRAMES = {
    "30": 30,
    "90": 90,
    "180": 180,
    "365": 365,
}
_DEFAULT_DAYS = 90


def _parse_filter_params(request: HttpRequest) -> tuple[int, list[str] | None]:
    """Extract lookback days and player list from query parameters."""
    days = _TIMEFRAMES.get(request.GET.get("days", ""), _DEFAULT_DAYS)
    raw_players = request.GET.get("players", "").strip()
    players = [p.strip() for p in raw_players.split(",") if p.strip()] or None
    return days, players


def _fmt_accuracy(value: float | None) -> str:
    """Format accuracy value as a percentage string."""
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_acpl(value: float | None) -> str:
    """Format centipawn loss value as a string."""
    return f"{value:.1f}" if value is not None else "—"


def _fmt_last_ingest(event: dict | None) -> str:
    """Format the timestamp of the last ingest event as a readable string."""
    if event is None:
        return "Never"
    ts = event.get("completed_at") or event.get("started_at")
    if ts is None:
        return "Unknown"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%b %d, %Y at %I:%M %p UTC")


@login_required
def index(request: HttpRequest) -> HttpResponse:
    """Render the main dashboard page with recent games and chart placeholders."""
    all_members = services.get_club_member_names()
    last_ingest = services.get_last_system_event("ingest")
    recent_games = services.get_most_recent_games(limit=10)

    return render(request, "dashboard/index.html", {
        "all_members": all_members,
        "all_members_json": json.dumps(all_members),
        "recent_games": recent_games,
        "last_check_time": _fmt_last_ingest(last_ingest),
        "timeframe_options": [
            ("30", "Last 30 days"),
            ("90", "Last 90 days"),
            ("180", "Last 6 months"),
            ("365", "Last year"),
        ],
    })


# ── HTMX partials ────────────────────────────────────────────────────────────

@login_required
@require_GET
def accuracy_chart_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with accuracy timeseries Plotly chart."""
    days, players = _parse_filter_params(request)
    df = services.get_player_accuracy_timeseries(lookback_days=days, players=players)

    chart_json = "{}"
    if not df.empty:
        fig = player_accuracy_chart(df)
        chart_json = fig.to_json()

    return render(request, "dashboard/partials/accuracy_chart.html", {
        "chart_json": chart_json,
        "empty": df.empty,
    })


@login_required
@require_GET
def elo_chart_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with ELO rating timeseries Plotly chart."""
    days, players = _parse_filter_params(request)
    df = services.get_all_players_elo_timeseries(lookback_days=days, players=players)

    chart_json = "{}"
    if not df.empty:
        fig = player_elo_chart(df)
        chart_json = fig.to_json()

    return render(request, "dashboard/partials/elo_chart.html", {
        "chart_json": chart_json,
        "empty": df.empty,
    })


@login_required
@require_GET
def sankey_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with opening moves Sankey diagram."""
    days, players = _parse_filter_params(request)
    edges_df, node_stats_df = services.get_opening_flow(
        lookback_days=days, players=players, min_games=2
    )

    chart_json = "{}"
    sankey_labels: list[str] = []

    if not edges_df.empty:
        # Trim to top 5 root openings (same logic as Streamlit page)
        all_targets = set(edges_df["target"])
        root_nodes = [s for s in edges_df["source"].unique() if s not in all_targets]
        if not node_stats_df.empty:
            root_games = (
                node_stats_df[node_stats_df["node"].isin(root_nodes)]
                .nlargest(5, "games")["node"]
                .tolist()
            )
            reachable: set[str] = set(root_games)
            for _ in range(3):
                reachable |= set(edges_df[edges_df["source"].isin(reachable)]["target"])
            edges_df = edges_df[
                edges_df["source"].isin(reachable) & edges_df["target"].isin(reachable)
            ].reset_index(drop=True)

        if not edges_df.empty:
            fig = welcome_opening_sankey(edges_df, node_stats_df)
            chart_json = fig.to_json()
            sankey_labels = list(dict.fromkeys(
                edges_df["source"].tolist() + edges_df["target"].tolist()
            ))

    return render(request, "dashboard/partials/sankey_chart.html", {
        "chart_json": chart_json,
        "sankey_labels_json": json.dumps(sankey_labels),
        "empty": edges_df.empty if not edges_df.empty else True,
    })


@login_required
@require_POST
def opening_node_stats_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with statistics for a selected opening node."""
    days, players = _parse_filter_params(request)
    node_label = request.POST.get("node", "").strip()

    node_stats: dict | None = None
    if node_label:
        _, node_stats_df = services.get_opening_flow(
            lookback_days=days, players=players, min_games=2
        )
        if not node_stats_df.empty:
            row = node_stats_df[node_stats_df["node"] == node_label]
            if not row.empty:
                node_stats = row.iloc[0].to_dict()

    return render(request, "dashboard/partials/opening_node_stats.html", {
        "node_label": node_label,
        "node_stats": node_stats,
    })


@login_required
@require_GET
def best_recent_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with highest-accuracy games from recent period."""
    days, players = _parse_filter_params(request)
    games = services.get_best_recent_games_by_accuracy(limit=10, lookback_days=30)
    if players:
        games = [
            g for g in games
            if g["white"].lower() in [p.lower() for p in players]
            or g["black"].lower() in [p.lower() for p in players]
        ]
    return render(request, "dashboard/partials/best_games_table.html", {
        "games": games,
        "table_title": "Best Played Games — Recent (30 days, by accuracy)",
        "show_acpl": False,
    })


@login_required
@require_GET
def best_alltime_partial(request: HttpRequest) -> HttpResponse:
    """Return HTML partial with lowest-ACPL games from all time."""
    games = services.get_best_all_time_games_by_acpl(limit=10)
    return render(request, "dashboard/partials/best_games_table.html", {
        "games": games,
        "table_title": "Best Club Games — All Time (by lowest ACPL)",
        "show_acpl": True,
    })
