"""Du Bois-styled Plotly chart builders for the dashboard."""

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
    "gilt": "#B8922A",
    "crimson": "#B53541",
    "scarlet": "#CE3A4A",
    "rose": "#E07B7B",
    "brilliant": "#2C6B4A",
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
    """Return a Du Bois-styled Plotly layout dict with optional overrides."""
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
            bgcolor="rgba(242,230,208,0.9)",
            bordercolor=_GP["ebony"], borderwidth=1,
            font=dict(family=_GP_FONT, color=_GP["ebony"], size=12),
        ),
    )
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
        else:
            base[k] = v
    return base


def player_accuracy_chart(df: pd.DataFrame) -> go.Figure:
    """Create a line chart showing accuracy trends for each player over time."""
    if df.empty:
        return go.Figure()
    fig = go.Figure()
    for i, player in enumerate(sorted(df["player"].unique())):
        pdata = df[df["player"] == player].sort_values("date")
        color = _GP_COLORWAY[i % len(_GP_COLORWAY)]
        fig.add_trace(go.Scatter(
            x=pdata["date"], y=pdata["accuracy"],
            mode="lines", name=player,
            line=dict(color=color, width=3.5),
            hovertemplate="%{fullData.name}<br>%{x|%d %b %Y}<br><b>%{y:.1f}%</b><extra></extra>",
        ))
    fig.update_layout(**_gp_layout(
        title_text="Average Accuracy by Player",
        legend_title="Player",
        margin=dict(l=20, r=20, t=56, b=20),
        hovermode="x unified",
        yaxis=dict(title="Accuracy (%)", range=[max(0, df["accuracy"].min() - 5), 100]),
    ))
    return fig


def player_elo_chart(df: pd.DataFrame) -> go.Figure:
    """Create a line chart showing ELO rating trends for each player over time."""
    if df.empty:
        return go.Figure()
    cleaned = []
    for player in df["player"].unique():
        pdata = df[df["player"] == player].sort_values("date").copy()
        pdata = pdata[pdata["rating"].diff().fillna(0) >= -100]
        cleaned.append(pdata)
    df = pd.concat(cleaned) if cleaned else df

    fig = go.Figure()
    for i, player in enumerate(sorted(df["player"].unique())):
        pdata = df[df["player"] == player].sort_values("date")
        color = _GP_COLORWAY[i % len(_GP_COLORWAY)]
        fig.add_trace(go.Scatter(
            x=pdata["date"], y=pdata["rating"],
            mode="lines", name=player,
            line=dict(color=color, width=3.5),
            hovertemplate="%{fullData.name}<br>%{x|%d %b %Y}<br><b>%{y:.0f}</b><extra></extra>",
        ))
    rating_min = df["rating"].min()
    rating_max = df["rating"].max()
    padding = max((rating_max - rating_min) * 0.05, 20)
    fig.update_layout(**_gp_layout(
        title_text="Average ELO by Player",
        legend_title="Player",
        margin=dict(l=20, r=20, t=56, b=20),
        hovermode="x unified",
        yaxis=dict(title="ELO Rating", range=[rating_min - padding, rating_max + padding]),
    ))
    return fig


def welcome_opening_sankey(
    edges_df: pd.DataFrame,
    node_stats_df: pd.DataFrame,
    selected_node: str | None = None,
    title: str = "Opening Continuations",
) -> go.Figure:
    """Create a Sankey diagram showing opening move continuations with statistics."""
    if edges_df.empty:
        return go.Figure()

    labels: list[str] = list(
        dict.fromkeys(edges_df["source"].tolist() + edges_df["target"].tolist())
    )
    idx_map = {label: i for i, label in enumerate(labels)}

    stats_lookup: dict[str, dict] = {}
    if not node_stats_df.empty:
        for _, row in node_stats_df.iterrows():
            stats_lookup[row["node"]] = row.to_dict()

    def _hex_rgba(hex_color: str, alpha: float) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"

    def _hover(label: str) -> str:
        s = stats_lookup.get(label, {})
        if not s:
            return label
        g = s.get("games", 0)
        wp, dp, lp = s.get("win_pct", 0), s.get("draw_pct", 0), s.get("loss_pct", 0)
        wa, ba = s.get("avg_white_accuracy"), s.get("avg_black_accuracy")
        acc_line = ""
        if wa is not None or ba is not None:
            parts = []
            if wa is not None:
                parts.append(f"W {wa:.0f}%")
            if ba is not None:
                parts.append(f"B {ba:.0f}%")
            acc_line = f"<br>Accuracy: {' · '.join(parts)}"
        players: dict = s.get("players") or {}
        player_lines = "".join(
            f"<br>{p}: {n}" for p, n in sorted(players.items(), key=lambda x: -x[1])
        )
        return (
            f"<b>{label}</b><br>{g} games<br>"
            f"W {wp:.0f}% · D {dp:.0f}% · L {lp:.0f}%"
            f"{acc_line}{player_lines}<extra></extra>"
        )

    selected_set: set[str] = set()
    neighbour_set: set[str] = set()
    if selected_node:
        selected_set.add(selected_node)
        for _, row in edges_df.iterrows():
            if row["source"] == selected_node:
                neighbour_set.add(row["target"])
            if row["target"] == selected_node:
                neighbour_set.add(row["source"])

    def _node_color(label: str) -> str:
        if label in selected_set:
            return _GP["whisky"]
        if selected_node and label not in neighbour_set:
            return _hex_rgba(_GP["crimson"], 0.25)
        return _GP["crimson"]

    def _link_color(src: str, tgt: str) -> str:
        if selected_node:
            if src in selected_set or tgt in selected_set:
                return _hex_rgba(_GP["whisky"], 0.55)
            return _hex_rgba(_GP["whisky"], 0.08)
        return _hex_rgba(_GP["whisky"], 0.35)

    fig = go.Figure(data=[go.Sankey(
        arrangement="snap",
        textfont=dict(family=_GP_MONO, size=12, color=_GP["ebony"]),
        node=dict(
            label=labels,
            customdata=labels,
            hovertemplate=[_hover(lbl) for lbl in labels],
            pad=24, thickness=22,
            color=[_node_color(lbl) for lbl in labels],
            line=dict(color=_GP["ebony"], width=1.5),
        ),
        link=dict(
            source=[idx_map[r["source"]] for _, r in edges_df.iterrows()],
            target=[idx_map[r["target"]] for _, r in edges_df.iterrows()],
            value=edges_df["games"].tolist(),
            color=[_link_color(r["source"], r["target"]) for _, r in edges_df.iterrows()],
            hovertemplate=(
                "<b>%{source.label}</b> → <b>%{target.label}</b><br>"
                "%{value} games<extra></extra>"
            ),
        ),
    )])
    fig.update_layout(**_gp_layout(
        title=title,
        margin=dict(l=10, r=10, t=64, b=20),
        height=540,
    ))
    return fig
