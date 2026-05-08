"""Du Bois-styled Plotly chart builders for the openings app."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

_GP = {
    "parchment": "#F2E6D0",
    "linen": "#E8D5B0",
    "ebony": "#1A1A1A",
    "forest": "#1A3A2A",
    "moss": "#4A6554",
    "whisky": "#D4A843",
    "peat": "#8B3A2A",
    "smoke": "#5A5A5A",
    "crimson": "#B53541",
    "steel": "#4A6E8A",
}

_GP_COLORWAY = [
    "#B53541", "#D4A843", "#4A6554", "#4A6E8A",
    "#8B3A2A", "#E07B7B", "#C4933F", "#2C6B4A",
]

_GP_FONT = "EB Garamond, Georgia, serif"
_GP_MONO = "DM Mono, Courier New, monospace"
_GP_TITLE = "Playfair Display SC, Cormorant Garamond, Georgia, serif"


def _gp_layout(**overrides) -> dict:
    """Return Du Bois-styled Plotly layout with optional overrides."""
    base: dict = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(242,230,208,0.5)",
        font=dict(family=_GP_FONT, color=_GP["ebony"], size=13),
        title_font=dict(family=_GP_TITLE, size=16, color=_GP["forest"]),
        colorway=_GP_COLORWAY,
        xaxis=dict(
            gridcolor=_GP["linen"], gridwidth=1,
            linecolor=_GP["ebony"], linewidth=2,
            tickfont=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            title_font=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            zerolinecolor=_GP["ebony"], zerolinewidth=2,
        ),
        yaxis=dict(
            gridcolor=_GP["linen"], gridwidth=1,
            linecolor=_GP["ebony"], linewidth=2,
            tickfont=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            title_font=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            zerolinecolor=_GP["ebony"], zerolinewidth=2,
        ),
        legend=dict(
            font=dict(family=_GP_MONO, color=_GP["smoke"], size=11),
            bgcolor="rgba(242,230,208,0.8)",
            bordercolor=_GP["ebony"],
            borderwidth=1,
        ),
        margin=dict(l=40, r=20, t=60, b=40),
    )
    base.update(overrides)
    return base


def opening_share_pie(
    share_df: pd.DataFrame,
    opening_name: str,
    scope_label: str | None = None,
) -> go.Figure:
    """Return a pie chart showing share of opening position in scoped games."""
    if share_df.empty:
        return go.Figure()

    title = (
        f"{opening_name} — Share of Scoped Games"
        if not scope_label
        else f"{opening_name} — Share ({scope_label})"
    )
    fig = go.Figure(
        data=go.Pie(
            labels=share_df["slice"].tolist(),
            values=share_df["games"].tolist(),
            hole=0.0,
            textposition="inside",
            textinfo="percent+label",
            textfont=dict(family=_GP_MONO, size=11),
            marker=dict(
                colors=[_GP["crimson"], _GP["linen"]],
                line=dict(color=[_GP["ebony"], _GP["smoke"]], width=2),
            ),
            hovertemplate="<b>%{label}</b><br>%{value} games (%{percent})<extra></extra>",
        )
    )
    fig.update_layout(
        **_gp_layout(title=title, showlegend=False, margin=dict(l=10, r=10, t=56, b=10), height=320)
    )
    return fig


def opening_player_accuracy_bar(
    stats_df: pd.DataFrame,
    opening_name: str,
    scope_label: str | None = None,
) -> go.Figure:
    """Return a horizontal bar chart of average accuracy by player in an opening."""
    df = stats_df.dropna(subset=["avg_accuracy"]).copy()
    if df.empty:
        return go.Figure()

    df = df.sort_values("avg_accuracy", ascending=True)
    title = (
        f"Average Accuracy by Player — {opening_name}"
        if not scope_label
        else f"Avg Accuracy — {opening_name} ({scope_label})"
    )
    fig = go.Figure(
        go.Bar(
            x=df["avg_accuracy"].tolist(),
            y=df["player"].tolist(),
            orientation="h",
            marker_color=_GP["whisky"],
            marker_line_color=_GP["ebony"],
            marker_line_width=1.5,
            text=[f"{v:.1f}%" for v in df["avg_accuracy"]],
            textposition="outside",
            textfont=dict(family=_GP_MONO, size=11, color=_GP["ebony"]),
            hovertemplate="<b>%{y}</b><br>Avg Accuracy: %{x:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        **_gp_layout(
            title=title,
            xaxis=dict(title="Accuracy (%)", range=[0, 105]),
            yaxis=dict(title=""),
            margin=dict(l=10, r=60, t=56, b=10),
            height=max(260, 60 + 50 * len(df)),
            showlegend=False,
        )
    )
    return fig


def opening_frequency_trend(
    freq_df: pd.DataFrame,
    opening_name: str,
    scope_label: str | None = None,
) -> go.Figure:
    """Return a line chart showing opening frequency over time by player."""
    if freq_df.empty:
        return go.Figure()

    title = (
        f"Opening Frequency Over Time — {opening_name}"
        if not scope_label
        else f"Frequency Over Time — {opening_name} ({scope_label})"
    )
    fig = go.Figure()
    players = sorted(freq_df["player"].unique())
    if "All selected games" in players:
        players = ["All selected games"] + [p for p in players if p != "All selected games"]

    for i, player in enumerate(players):
        pdata = freq_df[freq_df["player"] == player].sort_values("month")
        is_total = player == "All selected games"
        color = _GP["ebony"] if is_total else _GP_COLORWAY[i % len(_GP_COLORWAY)]
        fig.add_trace(
            go.Scatter(
                x=pdata["month"],
                y=pdata["games"],
                mode="lines",
                name=player,
                line=dict(
                    color=color,
                    width=3.8 if is_total else 3.2,
                    dash="dash" if is_total else "solid",
                ),
                hovertemplate=f"<b>{player}</b><br>%{{x|%b %Y}}<br><b>%{{y}} games</b><extra></extra>",
            )
        )

    fig.update_layout(
        **_gp_layout(
            title=title,
            xaxis=dict(title="Month"),
            yaxis=dict(title="Games", rangemode="tozero"),
            hovermode="x unified",
            legend_title="Player",
            margin=dict(l=10, r=10, t=56, b=10),
            height=320,
        )
    )
    return fig
