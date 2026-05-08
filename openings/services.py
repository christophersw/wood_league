"""Django ORM port of OpeningPositionService."""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from html import escape

import chess
import chess.pgn
import chess.svg
import pandas as pd
from django.db.models import Q

from analysis.models import GameAnalysis
from games.models import Game, GameParticipant
from openings.models import OpeningBook
from players.models import Player


# ── Opening book lookup cache ─────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_book() -> dict[str, tuple[str, str]]:
    """Load and cache opening book EPD→(eco, name) mapping once per process."""
    return {
        row["epd"]: (row["eco"], row["name"])
        for row in OpeningBook.objects.values("epd", "eco", "name")
    }


@lru_cache(maxsize=1)
def _load_book_entries() -> dict[str, tuple[int, str, str]]:
    """Load and cache opening book EPD→(id, eco, name) mapping once per process."""
    return {
        row["epd"]: (row["id"], row["eco"], row["name"])
        for row in OpeningBook.objects.values("id", "epd", "eco", "name")
    }


def lookup_opening(board: chess.Board) -> tuple[str, str] | None:
    """Return (eco, name) for the current board position, or None."""
    return _load_book().get(board.epd())


def lookup_opening_entry(board: chess.Board) -> tuple[int, str, str] | None:
    """Return (id, eco, name) for the current board position, or None."""
    return _load_book_entries().get(board.epd())


# ── Board colours ─────────────────────────────────────────────────────────────

_BOARD_COLORS = {
    "square light": "#F2E6D0",
    "square dark": "#4A8C62",
    "margin": "#1A1A1A",
    "coord": "#D4A843",
}


# ── Opening metadata ──────────────────────────────────────────────────────────

def _parse_opening_pgn(pgn_text: str) -> tuple[chess.Board, int]:
    """Parse PGN text and return final board and ply depth."""
    board = chess.Board()
    for token in pgn_text.split():
        token = token.rstrip(".")
        if not token or token[0].isdigit():
            continue
        try:
            board.push_san(token)
        except Exception:
            pass
    return board, board.ply()


def get_opening(opening_id: int) -> dict | None:
    """Retrieve opening by ID with ECO code, name, PGN, EPD, and final FEN."""
    try:
        ob = OpeningBook.objects.get(pk=opening_id)
    except OpeningBook.DoesNotExist:
        return None
    board, ply_depth = _parse_opening_pgn(ob.pgn or "")
    return {
        "id": ob.id,
        "eco": ob.eco,
        "name": ob.name,
        "pgn": ob.pgn or "",
        "epd": ob.epd or "",
        "ply_depth": ply_depth,
        "final_fen": board.fen(),
    }


def search_openings(query: str, limit: int = 30) -> list[dict]:
    """Search openings by name substring and return matching openings up to limit."""
    qs = (
        OpeningBook.objects
        .filter(name__icontains=query)
        .order_by("name")
        .values("id", "eco", "name")[:limit]
    )
    return list(qs)


# ── Game fetching ─────────────────────────────────────────────────────────────

def get_games(
    opening: dict,
    lookback_days: int | None = 90,
    players: list[str] | None = None,
) -> pd.DataFrame:
    """Return club-player games that passed through the opening position (EPD match)."""
    target_epd = opening["epd"]
    ply_depth = opening["ply_depth"]

    floor_date = (
        datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
        if lookback_days is not None
        else None
    )

    qs = (
        GameParticipant.objects
        .select_related("game", "player", "game__analysis")
        .filter(game__pgn__isnull=False)
        .exclude(game__pgn="")
        .order_by("-game__played_at")
    )
    if floor_date is not None:
        qs = qs.filter(game__played_at__gte=floor_date)
    if players:
        lower_players = [p.lower() for p in players]
        qs = qs.filter(
            Q(*[Q(player__username__iexact=p) for p in lower_players], _connector=Q.OR)
        )

    seen_game_epd: dict[str, bool] = {}

    def _matches(pgn_text: str, gid: str) -> bool:
        """Check if game PGN passes through the target opening position."""
        if gid in seen_game_epd:
            return seen_game_epd[gid]
        try:
            game = chess.pgn.read_game(io.StringIO(pgn_text))
            if game is None:
                seen_game_epd[gid] = False
                return False
            board = game.board()
            result = False
            for move in game.mainline_moves():
                board.push(move)
                if board.epd() == target_epd:
                    result = True
                    break
                if board.ply() > ply_depth:
                    break
        except Exception:
            result = False
        seen_game_epd[gid] = result
        return result

    seen_keys: set[tuple[str, str]] = set()
    records = []
    for gp in qs:
        g = gp.game
        key = (g.id, gp.player.username)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        if not _matches(g.pgn, g.id):
            continue
        analysis = getattr(g, "analysis", None)
        records.append({
            "game_id": g.id,
            "slug": g.slug or "",
            "played_at": g.played_at,
            "club_player": gp.player.username,
            "color": (gp.color or "").lower(),
            "result": gp.result or "",
            "white_username": g.white_username or "?",
            "black_username": g.black_username or "?",
            "white_accuracy": analysis.white_accuracy if analysis else None,
            "black_accuracy": analysis.black_accuracy if analysis else None,
            "white_acpl": analysis.white_acpl if analysis else None,
            "black_acpl": analysis.black_acpl if analysis else None,
            "player_rating": gp.player_rating,
            "opponent_rating": gp.opponent_rating,
            "result_pgn": g.result_pgn or "",
            "pgn": g.pgn or "",
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df["played_at"] = pd.to_datetime(df["played_at"], utc=True)
    return df


# ── Per-player stats ──────────────────────────────────────────────────────────

def player_stats(games_df: pd.DataFrame) -> pd.DataFrame:
    if games_df.empty:
        return pd.DataFrame()

    rows = []
    for player, grp in games_df.groupby("club_player"):
        g = len(grp)
        wins = int((grp["result"] == "Win").sum())
        draws = int((grp["result"] == "Draw").sum())
        losses = int((grp["result"] == "Loss").sum())

        acc_vals, acpl_vals = [], []
        for _, r in grp.iterrows():
            if r["color"] == "white" and pd.notna(r["white_accuracy"]):
                acc_vals.append(r["white_accuracy"])
            elif r["color"] == "black" and pd.notna(r["black_accuracy"]):
                acc_vals.append(r["black_accuracy"])
            if r["color"] == "white" and pd.notna(r["white_acpl"]):
                acpl_vals.append(r["white_acpl"])
            elif r["color"] == "black" and pd.notna(r["black_acpl"]):
                acpl_vals.append(r["black_acpl"])

        rows.append({
            "player": player,
            "games": g,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "win_pct": round(wins / g * 100, 1) if g else 0.0,
            "draw_pct": round(draws / g * 100, 1) if g else 0.0,
            "loss_pct": round(losses / g * 100, 1) if g else 0.0,
            "avg_accuracy": round(sum(acc_vals) / len(acc_vals), 1) if acc_vals else None,
            "avg_acpl": round(sum(acpl_vals) / len(acpl_vals), 1) if acpl_vals else None,
            "as_white": int((grp["color"] == "white").sum()),
            "as_black": int((grp["color"] == "black").sum()),
        })

    return pd.DataFrame(rows).sort_values("games", ascending=False).reset_index(drop=True)


# ── Opening share ─────────────────────────────────────────────────────────────

def opening_share(
    opening: dict,
    games_df: pd.DataFrame,
    lookback_days: int | None = 90,
    players: list[str] | None = None,
) -> pd.DataFrame:
    """Return pie chart data showing opening position share within scoped games."""
    this_opening_games = int(games_df["game_id"].nunique()) if not games_df.empty else 0
    total_scoped_games = _scoped_unique_game_count(lookback_days=lookback_days, players=players)

    if total_scoped_games <= 0:
        return pd.DataFrame(columns=["slice", "games"])

    other = max(total_scoped_games - this_opening_games, 0)
    return pd.DataFrame([
        {"slice": "This opening position", "games": this_opening_games},
        {"slice": "Other scoped games", "games": other},
    ])


def _scoped_unique_game_count(
    lookback_days: int | None,
    players: list[str] | None,
) -> int:
    """Count unique games matching scope filters (date and player)."""
    floor_date = (
        datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
        if lookback_days is not None
        else None
    )
    qs = (
        GameParticipant.objects
        .filter(game__pgn__isnull=False)
        .exclude(game__pgn="")
    )
    if floor_date is not None:
        qs = qs.filter(game__played_at__gte=floor_date)
    if players:
        lower_players = [p.lower() for p in players]
        qs = qs.filter(
            Q(*[Q(player__username__iexact=p) for p in lower_players], _connector=Q.OR)
        )
    return qs.values("game_id").distinct().count()


# ── Frequency over time ───────────────────────────────────────────────────────

def frequency_over_time(games_df: pd.DataFrame) -> pd.DataFrame:
    """Return opening frequency trend by player and month."""
    if games_df.empty:
        return pd.DataFrame(columns=["month", "player", "games"])

    df = games_df.copy()
    df["month"] = df["played_at"].dt.to_period("M").dt.start_time
    grouped = (
        df.groupby(["month", "club_player"], as_index=False)["game_id"]
        .count()
        .rename(columns={"game_id": "games", "club_player": "player"})
        .sort_values(["month", "player"])
    )
    totals = (
        df.groupby("month", as_index=False)["game_id"]
        .nunique()
        .rename(columns={"game_id": "games"})
    )
    totals["player"] = "All selected games"
    return pd.concat([grouped, totals], ignore_index=True)


# ── Continuation Sankey ───────────────────────────────────────────────────────

def continuation_flow(
    games_df: pd.DataFrame,
    opening: dict,
    min_games: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute Sankey flow edges and node statistics from opening continuations."""
    if games_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    target_epd = opening["epd"]
    ply_depth = opening["ply_depth"]
    opening_name = opening["name"]
    root_label = f"Start: {opening_name}"

    edge_counts: dict[tuple[str, str], int] = defaultdict(int)
    node_data: dict[str, dict] = {}
    seen_gids: set[str] = set()

    for _, row in games_df.iterrows():
        gid = row["game_id"]
        if gid in seen_gids:
            continue
        seen_gids.add(gid)

        try:
            game = chess.pgn.read_game(io.StringIO(row["pgn"]))
            if game is None:
                continue
            board = game.board()
            node = game

            for _ in range(ply_depth):
                if not node.variations:
                    break
                node = node.variations[0]
                board.push(node.move)

            if board.epd() != target_epd:
                continue

            continuation_names: list[str] = []
            for i in range(6):
                if not node.variations:
                    break
                node = node.variations[0]
                board.push(node.move)
                if (i + 1) % 2 == 0:
                    result = lookup_opening(board)
                    if result:
                        _, name = result
                        if continuation_names and ":" in name:
                            name = name.split(":", 1)[1].strip()
                        if len(name) > 36:
                            name = name[:35] + "…"
                        continuation_names.append(name)
                    else:
                        continuation_names.append(
                            continuation_names[-1] if continuation_names else opening_name
                        )

            if not continuation_names:
                continue

            path = [root_label]
            for depth, name in enumerate(continuation_names, start=1):
                suffix = "move" if depth == 1 else "moves"
                path.append(f"After +{depth} {suffix}: {name}")

        except Exception:
            continue

        result_val = row["result"]
        w_acc = row.get("white_accuracy")
        b_acc = row.get("black_accuracy")
        player = row["club_player"]

        for i in range(len(path) - 1):
            edge_counts[(path[i], path[i + 1])] += 1

        for label in path:
            if label not in node_data:
                node_data[label] = {
                    "games": 0, "wins": 0, "draws": 0, "losses": 0,
                    "white_acc_sum": 0.0, "white_acc_n": 0,
                    "black_acc_sum": 0.0, "black_acc_n": 0,
                    "players": defaultdict(int),
                }
            nd = node_data[label]
            nd["games"] += 1
            if result_val == "Win":
                nd["wins"] += 1
            elif result_val == "Draw":
                nd["draws"] += 1
            else:
                nd["losses"] += 1
            if pd.notna(w_acc):
                nd["white_acc_sum"] += float(w_acc)
                nd["white_acc_n"] += 1
            if pd.notna(b_acc):
                nd["black_acc_sum"] += float(b_acc)
                nd["black_acc_n"] += 1
            nd["players"][player] += 1

    if not edge_counts:
        return pd.DataFrame(), pd.DataFrame()

    edges_df = pd.DataFrame(
        [{"source": s, "target": t, "games": c} for (s, t), c in edge_counts.items()]
    )
    edges_df = edges_df[edges_df["games"] >= min_games].reset_index(drop=True)
    if edges_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    visible_nodes = set(edges_df["source"].tolist() + edges_df["target"].tolist())

    node_rows = []
    for label, nd in node_data.items():
        if label not in visible_nodes:
            continue
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

    return edges_df, pd.DataFrame(node_rows)


# ── Opening tree context (lineage + continuations) ────────────────────────────

def opening_tree_context(
    opening: dict,
    lookback_days: int | None = 90,
    players: list[str] | None = None,
    max_children: int = 8,
) -> dict:
    """Build opening lineage and continuation context for tree visualization."""
    scoped_games = _scoped_games(lookback_days=lookback_days, players=players)

    total_scoped_games = int(scoped_games["game_id"].nunique()) if not scoped_games.empty else 0

    lineage = _lineage_for_opening(opening)
    if not lineage:
        lineage = [{
            "opening_id": opening.get("id"),
            "eco": opening.get("eco", ""),
            "name": opening.get("name", "Unknown"),
            "label": f"{opening.get('eco', '')} {opening.get('name', 'Unknown')}".strip(),
            "epd": opening["epd"],
            "fen": opening["final_fen"],
        }]

    selected_epd = opening["epd"]
    selected_ply = int(opening["ply_depth"])

    lineage_game_counts: dict[str, int] = {n["epd"]: 0 for n in lineage}
    child_counts: dict[str, dict] = {}
    selected_games = 0

    for _, row in scoped_games.iterrows():
        pgn_text = str(row.get("pgn") or "")
        if not pgn_text:
            continue
        try:
            game = chess.pgn.read_game(io.StringIO(pgn_text))
        except Exception:
            game = None
        if game is None:
            continue

        board = game.board()
        seen_lineage_epds: set[str] = set()
        reached_selected = False
        selected_child: tuple[int, str, str, str, str] | None = None

        for move in game.mainline_moves():
            board.push(move)
            epd = board.epd()

            if epd in lineage_game_counts:
                seen_lineage_epds.add(epd)

            if epd == selected_epd:
                reached_selected = True
                continue

            if reached_selected and board.ply() > selected_ply:
                hit = lookup_opening_entry(board)
                if hit is None:
                    continue
                opening_id, eco, name = hit
                if board.epd() == selected_epd:
                    continue
                selected_child = (opening_id, board.epd(), board.fen(), eco, name)
                break

        for epd in seen_lineage_epds:
            lineage_game_counts[epd] += 1

        if reached_selected:
            selected_games += 1

        if selected_child is not None:
            c_id, c_epd, c_fen, c_eco, c_name = selected_child
            if c_epd not in child_counts:
                child_counts[c_epd] = {
                    "opening_id": c_id,
                    "eco": c_eco,
                    "name": c_name,
                    "epd": c_epd,
                    "fen": c_fen,
                    "games": 0,
                }
            child_counts[c_epd]["games"] += 1

    for n in lineage:
        g = lineage_game_counts.get(n["epd"], 0)
        n["games"] = int(g)
        n["pct_scoped"] = round((g / total_scoped_games * 100.0), 1) if total_scoped_games else 0.0

    children = sorted(child_counts.values(), key=lambda x: x["games"], reverse=True)
    if max_children > 0:
        children = children[:max_children]

    for c in children:
        c["label"] = f"{c['eco']} {c['name']}".strip()
        c["pct_selected"] = round((c["games"] / selected_games * 100.0), 1) if selected_games else 0.0

    return {
        "total_scoped_games": total_scoped_games,
        "selected_games": selected_games,
        "lineage": lineage,
        "children": children,
    }


def _lineage_for_opening(opening: dict) -> list[dict]:
    """Extract sequence of intermediate openings from opening PGN."""
    board = chess.Board()
    nodes: list[dict] = []
    seen_epds: set[str] = set()

    for token in str(opening.get("pgn") or "").split():
        token = token.rstrip(".")
        if not token or token[0].isdigit():
            continue
        try:
            board.push_san(token)
        except Exception:
            continue

        hit = lookup_opening_entry(board)
        if hit is None:
            continue
        opening_id, eco, name = hit
        epd = board.epd()
        if epd in seen_epds:
            continue
        seen_epds.add(epd)
        nodes.append({
            "opening_id": opening_id,
            "eco": eco,
            "name": name,
            "label": f"{eco} {name}".strip(),
            "epd": epd,
            "fen": board.fen(),
        })

    if not nodes or nodes[-1]["epd"] != opening["epd"]:
        nodes.append({
            "opening_id": opening.get("id"),
            "eco": opening.get("eco", ""),
            "name": opening.get("name", "Unknown"),
            "label": f"{opening.get('eco', '')} {opening.get('name', 'Unknown')}".strip(),
            "epd": opening["epd"],
            "fen": opening["final_fen"],
        })

    return nodes


def _scoped_games(
    lookback_days: int | None,
    players: list[str] | None,
) -> pd.DataFrame:
    """Retrieve games matching scope filters (date and player) with PGN and metadata."""
    floor_date = (
        datetime.now(tz=timezone.utc) - timedelta(days=lookback_days)
        if lookback_days is not None
        else None
    )
    qs = (
        GameParticipant.objects
        .select_related("game", "player")
        .filter(game__pgn__isnull=False)
        .exclude(game__pgn="")
        .order_by("-game__played_at")
    )
    if floor_date is not None:
        qs = qs.filter(game__played_at__gte=floor_date)
    if players:
        lower_players = [p.lower() for p in players]
        qs = qs.filter(
            Q(*[Q(player__username__iexact=p) for p in lower_players], _connector=Q.OR)
        )

    seen_ids: set[str] = set()
    out: list[dict] = []
    for gp in qs:
        gid = gp.game_id
        if gid in seen_ids:
            continue
        seen_ids.add(gid)
        out.append({
            "game_id": gid,
            "pgn": gp.game.pgn or "",
            "played_at": gp.game.played_at,
        })
    if not out:
        return pd.DataFrame(columns=["game_id", "pgn", "played_at"])
    return pd.DataFrame(out)


# ── SVG opening tree renderer ─────────────────────────────────────────────────

import base64  # noqa: E402  (import after stdlib section is fine for clarity)


def opening_tree_svg(tree_ctx: dict, opening_epd: str) -> tuple[str, int]:
    """Render opening tree (lineage and continuations) as SVG with coordinates."""
    import chess.svg as _chess_svg

    lineage = tree_ctx.get("lineage", [])
    children = tree_ctx.get("children", [])

    if not lineage:
        return "", 0

    NW, NH = 248, 110
    BOARD_SZ = 94
    H_GAP = 54
    V_GAP = 14
    FORK_GAP = 72
    LABEL_H = 22
    PAD = 22

    def _board_img_href(fen: str | None) -> str | None:
        """Encode board position as base64-embedded SVG data URL."""
        if not fen:
            return None
        try:
            board = chess.Board(fen)
            svg_str = _chess_svg.board(board, size=BOARD_SZ, colors=_BOARD_COLORS, coordinates=False)
            encoded = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
            return f"data:image/svg+xml;base64,{encoded}"
        except Exception:
            return None

    n_lin = len(lineage)
    n_ch = len(children)

    ch_col_h = max(0, n_ch * NH + max(0, n_ch - 1) * V_GAP)
    content_h = max(NH, ch_col_h)
    canvas_h = LABEL_H + PAD + content_h + PAD

    lin_top = LABEL_H + PAD + (content_h - NH) / 2
    lin_cy = lin_top + NH / 2
    ch_top = LABEL_H + PAD + (content_h - ch_col_h) / 2

    lin_xs = [PAD + i * (NW + H_GAP) for i in range(n_lin)]
    cur_right = lin_xs[-1] + NW
    ch_x = cur_right + FORK_GAP
    canvas_w = (ch_x + NW + PAD) if n_ch > 0 else (cur_right + PAD)

    edge_gs = [lineage[i]["games"] for i in range(1, n_lin)] + [c["games"] for c in children]
    raw_max = max(edge_gs) if edge_gs else 0
    max_g = raw_max if raw_max > 0 else 1

    def _sw(g: int) -> float:
        """Calculate stroke width based on game count."""
        return max(1.5, min(10.0, 1.5 + (g / max_g) * 8.5))

    def _so(g: int) -> float:
        """Calculate stroke opacity based on game count."""
        return max(0.2, min(0.95, 0.2 + (g / max_g) * 0.75))

    def _wrap(text: str, max_chars: int = 20) -> list[str]:
        """Wrap text to max width with word boundaries, up to 2 lines."""
        words, lines, cur = text.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines.append(cur)
        return lines[:2]

    p: list[str] = []
    p.append(
        f'<svg width="{canvas_w:.0f}" height="{canvas_h:.0f}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;max-width:100%;overflow-x:auto">'
    )
    p.append(f'<rect width="{canvas_w:.0f}" height="{canvas_h:.0f}" fill="#F9F3E8"/>')

    lin_lbl_cx = lin_xs[0] + (lin_xs[-1] + NW - lin_xs[0]) / 2
    p.append(
        f'<text x="{lin_lbl_cx:.0f}" y="14" text-anchor="middle" '
        f'font-family="monospace" font-size="9" letter-spacing="2" '
        f'fill="#8B3A2A" opacity="0.55" font-weight="600">LINEAGE</text>'
    )
    if n_ch > 0:
        p.append(
            f'<text x="{ch_x + NW / 2:.0f}" y="14" text-anchor="middle" '
            f'font-family="monospace" font-size="9" letter-spacing="2" '
            f'fill="#1A3A2A" opacity="0.55" font-weight="600">CONTINUATIONS</text>'
        )

    for i in range(n_lin - 1):
        x1, x2 = lin_xs[i] + NW, lin_xs[i + 1]
        g = lineage[i + 1]["games"]
        p.append(
            f'<line x1="{x1:.1f}" y1="{lin_cy:.1f}" x2="{x2:.1f}" y2="{lin_cy:.1f}" '
            f'stroke="#D4A843" stroke-width="{_sw(g):.1f}" '
            f'stroke-opacity="{_so(g):.2f}" stroke-linecap="round"/>'
        )

    for j, child in enumerate(children):
        cy2 = ch_top + j * (NH + V_GAP) + NH / 2
        g = child["games"]
        cp1x = cur_right + (ch_x - cur_right) * 0.4
        cp2x = cur_right + (ch_x - cur_right) * 0.6
        p.append(
            f'<path d="M{cur_right:.1f},{lin_cy:.1f} '
            f'C{cp1x:.1f},{lin_cy:.1f} {cp2x:.1f},{cy2:.1f} {ch_x:.1f},{cy2:.1f}" '
            f'stroke="#1A3A2A" stroke-width="{_sw(g):.1f}" '
            f'stroke-opacity="{_so(g):.2f}" fill="none" stroke-linecap="round"/>'
        )

    def _node(node: dict, x: float, y: float, *, is_current: bool = False, is_child: bool = False) -> None:
        """Render a single opening node as SVG group with board image and text labels."""
        oid = node.get("opening_id")
        eco = str(node.get("eco") or "").upper()
        raw_name = str(node.get("name") or "Unknown")
        games = int(node.get("games") or 0)
        fen = node.get("fen") or node.get("epd")
        name_lines = _wrap(raw_name)

        if is_current:
            fill, stroke, sw_b = "#1A3A2A", "#D4A843", "3"
            ec, nc, gc = "#D4A843", "#F2E6D0", "#7EAD8A"
            board_border = "#D4A843"
        elif is_child:
            fill, stroke, sw_b = "#EFE4CC", "#1A1A1A", "1.5"
            ec, nc, gc = "#8B3A2A", "#1A3A2A", "#5A5A5A"
            board_border = "#1A1A1A"
        else:
            fill, stroke, sw_b = "#F2E6D0", "#1A1A1A", "1.5"
            ec, nc, gc = "#8B3A2A", "#1A3A2A", "#5A5A5A"
            board_border = "#1A1A1A"

        if oid:
            url = f"/openings/{oid}/"
            open_tag = f'<a href="{url}" style="cursor:pointer"><g class="ot-node">'
            close_tag = "</g></a>"
        else:
            open_tag = '<g class="ot-node">'
            close_tag = "</g>"

        bx = x + NW - BOARD_SZ - 6
        by = y + (NH - BOARD_SZ) / 2
        img_href = _board_img_href(fen)

        p.append(open_tag)
        p.append(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{NW}" height="{NH}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw_b}"/>'
        )
        if img_href:
            p.append(
                f'<rect x="{bx:.0f}" y="{by:.0f}" width="{BOARD_SZ}" height="{BOARD_SZ}" '
                f'fill="none" stroke="{board_border}" stroke-width="1" opacity="0.4"/>'
            )
            p.append(
                f'<image x="{bx:.0f}" y="{by:.0f}" width="{BOARD_SZ}" height="{BOARD_SZ}" '
                f'href="{img_href}" preserveAspectRatio="xMidYMid meet"/>'
            )
        p.append(
            f'<text x="{x + 10:.0f}" y="{y + 16:.0f}" '
            f'font-family="monospace" font-size="9" letter-spacing="1.5" '
            f'font-weight="600" fill="{ec}">{escape(eco)}</text>'
        )
        for k, line in enumerate(name_lines):
            p.append(
                f'<text x="{x + 10:.0f}" y="{y + 32 + k * 16:.0f}" '
                f'font-family="Georgia,serif" font-size="12" fill="{nc}">{escape(line)}</text>'
            )
        p.append(
            f'<text x="{x + 10:.0f}" y="{y + NH - 13:.0f}" '
            f'font-family="monospace" font-size="9" fill="{gc}">{games} games</text>'
        )
        p.append(close_tag)

    for i, node in enumerate(lineage):
        _node(node, lin_xs[i], lin_top, is_current=(node.get("epd") == opening_epd))

    for j, child in enumerate(children):
        _node(child, ch_x, ch_top + j * (NH + V_GAP), is_child=True)

    p.append("</svg>")
    return "".join(p), int(canvas_h)
