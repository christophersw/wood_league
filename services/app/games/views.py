"""
Title: views.py — Game analysis page views
Description:
    Handles rendering and HTMX partial responses for the game analysis page,
    including the main page view, the HTMX board partial (supports orientation
    flip without full reload), and the queue-analysis POST endpoint.

Changelog:
    2026-05-05 (#16): Highlighted every Engine Lines continuation move with the
                      shared best-move board color
    2026-05-05 (#16): Highlighted the first Engine Lines frame using the
                      move-quality board palette for the clicked move
    2026-05-05 (#16): Reworked engine-line continuations to use stored PV SAN data
                      and removed brittle continuation reconstruction logic
    2026-05-04 (#16): Full rewrite for ply-sync architecture; added board_partial
                      and queue_analysis views; removed build_board_viewer_html usage
"""

import io as _io
import json
import re

import chess
import chess.pgn as _pgn
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from analysis.models import AnalysisJob
from games.board_builder import _BOARD_COLORS, board_colors_for_move_classification, build_board_frames
from games.models import Game
from games.services import MoveRow, get_game_analysis
from games.stat_cards import _DUB_CSS, build_lc0_card, build_sf_card
from openings.models import OpeningBook

_ACTIVE_STATUSES = [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_SUBMITTED,
    AnalysisJob.STATUS_RUNNING,
]


def _humanize_time_control(time_control: str) -> str:
    """
    Convert time control to human-readable format.

    Handles two formats:
    - "x/y" (PGN format where y is total seconds): e.g., "1/259200" → "3 days"
    - "x+y" (clock format in minutes): e.g., "600+0" → "600+0" (unchanged)

    Params:
        time_control (str): Time control string.

    Returns:
        Human-readable time control string.
    """
    if not time_control:
        return ""
    
    # Handle PGN format "x/y" where y is seconds
    if "/" in time_control:
        try:
            parts = time_control.split("/")
            if len(parts) == 2:
                seconds = int(parts[1])
                # Convert to human-readable format
                if seconds >= 86400:  # 1 day = 86400 seconds
                    days = seconds // 86400
                    return f"{days}d"
                elif seconds >= 3600:  # 1 hour
                    hours = seconds // 3600
                    return f"{hours}h"
                elif seconds >= 60:  # 1 minute
                    minutes = seconds // 60
                    return f"{minutes}m"
                else:
                    return f"{seconds}s"
        except (ValueError, IndexError):
            pass
    
    # Return as-is if we can't parse it
    return time_control


def _details_string(data) -> str:
    """
    Build the date · time-control details string for the page header.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        String like "2024-03-15 14:30 · 600+0" or "2024-03-15 · 3d", or empty string.
    """
    parts = []
    if data.date:
        parts.append(data.date)
    if data.time_control:
        parts.append(_humanize_time_control(data.time_control))
    return " · ".join(parts)


def _opening_label(data) -> str:
    """
    Build a human-readable opening label from the game's ECO and name fields.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        Opening label string, preferring lichess_opening name when available,
        then looking up from OpeningBook by ECO code, skipping move notation.
    """
    def is_move_notation(name: str) -> bool:
        """Check if a string looks like chess move notation rather than an opening name."""
        if not name:
            return False
        # Move notation contains only chess-related chars: files (a-h), ranks (1-8),
        # pieces (KQRBN), capture (x), checks/mates (+#), spaces, etc.
        only_move_chars = bool(re.match(r"^[a-hKQRBNx\d\-\+#!? ]+$", name))
        # And must start with a move pattern (e.g., e4, Nf3, exd4)
        starts_with_move = bool(re.match(r"^([a-h][x]?[a-h]?\d|[KQRBN])", name))
        return only_move_chars and starts_with_move
    
    # Prefer lichess_opening if available
    if data.lichess_opening:
        if data.eco_code:
            return f"{data.eco_code} · {data.lichess_opening}"
        return data.lichess_opening
    
    # Use opening_name if it's not move notation
    if data.eco_code and data.opening_name and not is_move_notation(data.opening_name):
        return f"{data.eco_code} · {data.opening_name}"
    
    # Fall back to looking up the opening by ECO code from OpeningBook
    if data.eco_code:
        try:
            opening = OpeningBook.objects.filter(eco=data.eco_code).values_list("name", flat=True).first()
            if opening:
                return f"{data.eco_code} · {opening}"
        except Exception:
            pass
    
    return data.eco_code or ""


def _queue_status(slug: str) -> tuple[bool, bool]:
    """
    Check whether Stockfish or Lc0 analysis is currently queued for this game.

    Params:
        slug (str): Game URL slug.

    Returns:
        Tuple of (sf_queued, lc0_queued) booleans.
    """
    active = AnalysisJob.objects.filter(
        game__slug=slug,
        status__in=_ACTIVE_STATUSES,
    ).values_list("engine", flat=True)
    engines = set(active)
    return ("stockfish" in engines), ("lc0" in engines)


def _build_eval_json(data) -> str:
    """
    Serialize Stockfish per-move evaluation data as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, cp_eval, san, classification}] or "null".
    """
    if not (data.has_sf and data.moves):
        return "null"
    rows = [
        {
            "ply": r.ply,
            "cp_eval": r.cp_eval,
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in data.moves
        if r.cp_eval is not None
    ]
    return json.dumps(rows)


def _build_wdl_json(data) -> str:
    """
    Serialize Lc0 per-move WDL data as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, wdl_win, wdl_draw, wdl_loss, san, classification}] or "null".
    """
    if not data.lc0_moves:
        return "null"
    rows = [
        {
            "ply": r.ply,
            "wdl_win": r.wdl_win or 0,
            "wdl_draw": r.wdl_draw or 0,
            "wdl_loss": r.wdl_loss or 0,
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in data.lc0_moves
        if r.wdl_win is not None
    ]
    return json.dumps(rows)


def _parse_pv_san_moves(raw_pv_san: str | None) -> list[str]:
    """
    Parse stored PV SAN data into an ordered list of SAN moves.

    Params:
        raw_pv_san (str | None): Stored PV SAN payload, usually a JSON-encoded list.

    Returns:
        List of SAN moves in continuation order.
    """
    if not raw_pv_san:
        return []

    try:
        parsed = json.loads(raw_pv_san)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = raw_pv_san

    if isinstance(parsed, list):
        return [str(move).strip() for move in parsed if str(move).strip()]

    if isinstance(parsed, str):
        without_move_numbers = re.sub(r"\d+\.(?:\.\.)?", " ", parsed)
        return [token.strip() for token in without_move_numbers.split() if token.strip() and token.strip() != "*"]

    return []


def _engine_row_for_request(
    data,
    engine: str,
    analysis_ply: int,
) -> MoveRow | None:
    """
    Return the engine-analysis row that corresponds to the selected move ply.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        engine (str): "sf" or "lc0".
        analysis_ply (int): Absolute ply of the move being explored.

    Returns:
        Matching MoveRow, or None when unavailable.
    """
    move_rows = data.moves if engine == "sf" else (data.lc0_moves or [])
    for row in move_rows:
        if row.ply == analysis_ply:
            return row
    return None


def _continuation_san_moves_from_row(
    move_row: MoveRow | None,
    tier: int,
    clicked_move_san: str,
) -> list[str]:
    """
    Return stored continuation SAN moves for the selected engine tier.

    Params:
        move_row (MoveRow | None): Analysis row for the explored move.
        tier (int): Suggested move rank (1-3).
        clicked_move_san (str): SAN for the clicked move in the source position.

    Returns:
        Continuation SAN moves after the clicked move itself.
    """
    if move_row is None:
        return []

    pv_by_tier = {
        1: move_row.pv_san_1,
        2: move_row.pv_san_2,
        3: move_row.pv_san_3,
    }
    pv_moves = _parse_pv_san_moves(pv_by_tier.get(tier))
    if not pv_moves:
        return []
    if pv_moves[0] == clicked_move_san:
        return pv_moves[1:]
    return pv_moves


def _fallback_game_continuation_sans(
    moves_list: list[chess.Move],
    request_ply: int,
) -> list[chess.Move]:
    """
    Return remaining game moves after the selected move index as a fallback line.

    Params:
        moves_list (list[chess.Move]): Mainline moves from the source game.
        request_ply (int): Zero-based ply count before the clicked move.

    Returns:
        Remaining game moves after the selected move.
    """
    return list(moves_list[request_ply + 1:])


def _build_pgn_moves_json(data) -> str:
    """
    Serialize the move list for the client-side PGN table as a JSON string.

    Params:
        data (GameAnalysisData): Assembled game analysis data.

    Returns:
        JSON string of [{ply, move_number, color, san, classification}].
    """
    rows = [
        {
            "ply": r.ply,
            "move_number": (r.ply + 1) // 2,
            "color": "white" if r.ply % 2 == 1 else "black",
            "san": r.san,
            "classification": r.classification or "",
        }
        for r in (data.moves or [])
    ]
    return json.dumps(rows)


def game_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """
    Render the main game analysis page.

    Loads game and analysis data, builds engine stat cards and serialized
    chart/PGN data for client-side rendering. The board itself is loaded
    via HTMX (board_partial view) so orientation changes don't reload the page.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered analysis.html with full context, or analysis.html with
        no_data=True if the game has no parseable PGN or analysis.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    if data is None or not data.moves:
        return render(request, "games/analysis.html", {
            "game": game,
            "no_data": True,
        })

    initial_ply = 0
    try:
        initial_ply = max(0, int(request.GET.get("ply", 0)))
    except (ValueError, TypeError):
        pass

    initial_perspective = request.GET.get("orientation", "white")
    if initial_perspective not in ("white", "black"):
        initial_perspective = "white"

    sf_queued, lc0_queued = _queue_status(slug)
    engine_cards_html = _DUB_CSS + build_sf_card(data, queued=sf_queued) + build_lc0_card(data, queued=lc0_queued)

    return render(request, "games/analysis.html", {
        "game": game,
        "data": data,
        "no_data": False,
        "details": _details_string(data),
        "opening_label": _opening_label(data),
        "opening_id": data.opening_id,
        "chesscom_url": data.url,
        "engine_cards_html": engine_cards_html,
        "sf_eval_json": _build_eval_json(data),
        "lc0_wdl_json": _build_wdl_json(data),
        "pgn_moves_json": _build_pgn_moves_json(data),
        "initial_ply": initial_ply,
        "initial_perspective": initial_perspective,
        "has_sf": data.has_sf,
        "has_lc0": data.has_lc0,
        "white": data.white,
        "black": data.black,
    })


def board_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """
    HTMX partial: render the interactive board for a given orientation.

    Called on initial page load (hx-trigger="load") and on board flip.
    Generates all SVG frames server-side and embeds them as JSON in the
    response so client-side JS can animate without further requests.

    Params:
        request (HttpRequest): The HTTP request; reads ?orientation= GET param.
        slug (str): Game URL slug.

    Returns:
        Rendered _board_partial.html, or a minimal error partial if no data.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    orientation = request.GET.get("orientation", "white")
    if orientation not in ("white", "black"):
        orientation = "white"

    if data is None or not data.moves:
        return render(request, "games/_board_error_partial.html", {"game": game})

    board_data = build_board_frames(data, size=480, orientation=orientation)

    # Build is_best_map: ply → True if the player's move matched SF best move
    sf_by_ply = {row.ply: row for row in data.moves}
    game_obj = _pgn.read_game(_io.StringIO(data.pgn))
    is_best_map: dict[int, bool] = {}
    if game_obj:
        _board = game_obj.board()
        _start = _board.ply()
        _board = game_obj.board()
        for _ply_i, _move in enumerate(game_obj.mainline_moves(), start=1):
            _abs = _ply_i + _start
            _row = sf_by_ply.get(_abs) or sf_by_ply.get(_ply_i)
            if _row and _row.arrow_uci:
                is_best_map[_ply_i] = _move.uci() == _row.arrow_uci
            _board.push(_move)

    return render(request, "games/_board_partial.html", {
        "slug": slug,
        "orientation": orientation,
        "frames_json": json.dumps(board_data["frames"]),
        "arrow_data_json": json.dumps(board_data["arrows_by_ply"]),
        "san_list_json": json.dumps(board_data["san_list"]),
        "is_best_json": json.dumps(is_best_map),
        "total_frames": board_data["total_frames"],
        "top_player": board_data["top_player"],
        "top_sym": board_data["top_sym"],
        "top_side": board_data["top_side"],
        "bottom_player": board_data["bottom_player"],
        "bottom_sym": board_data["bottom_sym"],
        "bottom_side": board_data["bottom_side"],
        "has_sf": board_data["has_sf"],
        "has_lc0": board_data["has_lc0"],
        "overlay_viewbox_size": board_data["overlay_geometry"]["viewbox_size"],
        "overlay_board_margin": board_data["overlay_geometry"]["board_margin"],
        "overlay_square_size": board_data["overlay_geometry"]["square_size"],
        "no_arrows": False,
    })


def engine_line_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """
    HTMX partial: render an engine line continuation board.

    Called when user clicks an arrow on the main board. Reconstructs the board position
    at the given ply, plays the specified move, and continues from there, displaying
    up to 50+ moves of continuation.

    Query params:
        ply (int): Starting ply in the main game (before the clicked move).
        move_uci (str): The UCI move to play (the clicked arrow).
        engine (str): "sf" or "lc0" (which engine suggested this move).
        tier (int): 1, 2, or 3 (which tier of suggestion this was).
        orientation (str): "white" or "black" (perspective, must match main board).

    Returns:
        Rendered _engine_line_partial.html with the continuation board frames,
        or error partial if unable to reconstruct position or find continuation data.
    """
    game = get_object_or_404(Game, slug=slug)
    data = get_game_analysis(slug)

    if data is None or not data.moves or not data.pgn:
        return render(request, "games/_board_error_partial.html", {"game": game})

    try:
        ply = int(request.GET.get("ply", 0))
    except (ValueError, TypeError):
        ply = 0
    ply = max(0, ply)

    move_uci = request.GET.get("move_uci", "").strip()
    if not move_uci or len(move_uci) < 4:
        return HttpResponse("Invalid move_uci", status=400)

    engine = request.GET.get("engine", "sf").strip().lower()
    if engine not in ("sf", "lc0"):
        engine = "sf"

    try:
        tier = int(request.GET.get("tier", 1))
    except (ValueError, TypeError):
        tier = 1
    tier = max(1, min(3, tier))
    delta_label = request.GET.get("delta_label", "").strip()

    orientation = request.GET.get("orientation", "white")
    if orientation not in ("white", "black"):
        orientation = "white"

    # Reconstruct board position up to the given ply
    game_obj = _pgn.read_game(_io.StringIO(data.pgn))
    if game_obj is None:
        return HttpResponse("Cannot parse PGN", status=400)

    board = game_obj.board()
    start_ply_offset = board.ply()
    moves_list = list(game_obj.mainline_moves())

    # Move the board to the selected pre-move position.
    for move in moves_list[:ply]:
        board.push(move)

    clicked_move_san = ""
    try:
        clicked_move = board.parse_uci(move_uci)
        clicked_move_san = board.san(clicked_move)
        board.push(clicked_move)
    except (ValueError, AssertionError):
        return HttpResponse("Invalid move_uci for position", status=400)

    analysis_ply = start_ply_offset + ply + 1
    context_parts = ["Best" if tier == 1 else f"Move {tier}"]
    context_parts.append(engine.upper())
    context_parts.append(f"(ply {analysis_ply})")
    if delta_label:
        context_parts.append(delta_label)
    context_label = " ".join(context_parts)

    flipped = orientation == "black"
    frames = []
    san_list = []
    arrow_labels_by_ply = {}

    # Frame 0: position after the clicked move, with that move highlighted clearly.
    frames.append(chess.svg.board(
        board,
        size=480,
        lastmove=clicked_move,
        flipped=flipped,
        colors=board_colors_for_move_classification("best"),
    ))

    continuation_board = board.copy()
    move_row = _engine_row_for_request(data, engine, analysis_ply)
    continuation_sans = _continuation_san_moves_from_row(move_row, tier, clicked_move_san)

    if continuation_sans:
        for san in continuation_sans:
            try:
                continuation_move = continuation_board.parse_san(san)
            except (ValueError, AssertionError):
                break

            continuation_board.push(continuation_move)
            san_list.append(san)
            frames.append(chess.svg.board(
                continuation_board,
                size=480,
                lastmove=continuation_move,
                flipped=flipped,
                colors=board_colors_for_move_classification("best"),
            ))
    else:
        for move in _fallback_game_continuation_sans(moves_list, ply)[:50]:
            try:
                san = continuation_board.san(move)
                continuation_board.push(move)
            except (ValueError, AssertionError):
                break

            san_list.append(san)
            frames.append(chess.svg.board(
                continuation_board,
                size=480,
                lastmove=move,
                flipped=flipped,
                colors=board_colors_for_move_classification("best"),
            ))

    return render(request, "games/_engine_line_partial.html", {
        "frames_json": json.dumps(frames),
        "arrow_labels_json": json.dumps(arrow_labels_by_ply),
        "san_list_json": json.dumps(san_list),
        "context_label": context_label,
        "total_frames": len(frames),
    })


def queue_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """
    Queue a game for engine re-analysis.

    Accepts engine="stockfish" or engine="lc0" in the POST body. Enforces
    that a game cannot be queued if an active job already exists for that engine.

    Params:
        request (HttpRequest): POST request with engine field.
        slug (str): Game URL slug.

    Returns:
        HTMX partial HTML fragment: success or already-queued button state.
        Returns 400 for invalid engine values.
    """
    engine = request.POST.get("engine", "").strip().lower()
    if engine not in ("stockfish", "lc0"):
        return HttpResponse("Invalid engine", status=400)

    game = get_object_or_404(Game, slug=slug)

    already_queued = AnalysisJob.objects.filter(
        game=game,
        engine=engine,
        status__in=_ACTIVE_STATUSES,
    ).exists()

    if already_queued:
        return render(request, "games/_queue_already_queued.html", {"engine": engine})

    # Use Django settings for analysis depth
    if engine == "lc0":
        depth = settings.LC0_NODES
    else:
        depth = settings.ANALYSIS_DEPTH
    
    AnalysisJob.objects.create(
        game=game,
        engine=engine,
        status=AnalysisJob.STATUS_PENDING,
        priority=1,
        depth=depth,
    )
    return render(request, "games/_queue_success.html", {"engine": engine})
