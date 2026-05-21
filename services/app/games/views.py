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
    2026-05-21 (#186): Wire card_sf_partial to build_sf_card_context; import cards module.
    2026-05-21 (#186): Wire card_lc0_partial to build_lc0_card_context with side_labels.
    2026-05-21 (#186): Wire chart_winpct_partial to winpct_payload from chart_data.
    2026-05-21 (#186): Wire chart_sf_cp_partial to sf_cp_payload from chart_data.
    2026-05-21 (#186): Wire chips_partial to chips_for_ply from chip_data.
    2026-05-21 (#186): Task 14 — wire pgn_partial to walk PGN mainline and attach SF classifications.
    2026-05-21 (#186): Task 15 — drop dead helpers (_humanize_time_control, _details_string,
                      _opening_label, _queue_status, _build_eval_json, _build_wdl_json,
                      _build_pgn_moves_json) and OpeningBook import; stat_cards.py deleted.
"""

import io as _io
import json
import re

import chess
import chess.pgn as _pgn
from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from analysis.models import AnalysisJob
from games.board_builder import board_colors_for_move_classification, build_board_frames
from games.models import Game
from games.services import MoveRow, get_game_analysis
from games.cards import build_lc0_card_context, build_sf_card_context
from games.chart_data import lc0_wdl_payload, sf_cp_payload, winpct_payload
from games.chip_data import chips_for_ply
from games.services_v2 import get_game_analysis_v2
_ACTIVE_STATUSES = [
    AnalysisJob.STATUS_PENDING,
    AnalysisJob.STATUS_SUBMITTED,
    AnalysisJob.STATUS_RUNNING,
]


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


def game_analysis(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the thin shell for the analysis page.

    Each visual unit is loaded by HTMX from its own partial URL.
    Uses get_game_analysis_v2 which returns None for legacy (pre-new-schema)
    games, triggering a re-analyze banner instead of the analysis shell.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered analysis.html thin shell with HTMX partial slots, or
        analysis.html with no_data=True and reanalyze=True for legacy games.
    """
    try:
        game = Game.objects.get(slug=slug)
    except Game.DoesNotExist:
        raise Http404
    data = get_game_analysis_v2(slug)
    if data is None:
        return render(request, "games/analysis.html", {
            "game": game, "no_data": True, "reanalyze": True,
        })
    initial_ply = int(request.GET.get("ply", 0) or 0)
    initial_perspective = request.GET.get("perspective", "white")
    if initial_perspective not in {"white", "black"}:
        initial_perspective = "white"
    return render(request, "games/analysis.html", {
        "game": game,
        "data": data,
        "no_data": False,
        "initial_ply": initial_ply,
        "initial_perspective": initial_perspective,
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
    arrow_labels_by_ply: dict[int, list[str]] = {}

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
        priority=AnalysisJob.PRIORITY_HIGH,
        depth=depth,
    )
    return render(request, "games/_queue_success.html", {"engine": engine})


def _load_or_404(slug: str):
    """Load game analysis data or raise Http404 if not available.

    Returns GameAnalysisDataV2 when the game has new-schema analysis.
    Raises Http404 if the game doesn't exist or has no new-schema analysis.
    """
    data = get_game_analysis_v2(slug)
    if data is None:
        raise Http404
    return data


def card_sf_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the Stockfish card partial.

    Builds the SF card context via build_sf_card_context and passes
    per-side labels so the template can loop over White and Black.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered _card_sf.html partial with SF stats context.
    """
    data = _load_or_404(slug)
    ctx = build_sf_card_context(data)
    ctx["side_labels"] = [("white", data.white), ("black", data.black)]
    ctx["data"] = data
    return render(request, "games/partials/_card_sf.html", ctx)


def card_lc0_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the LC0 stat card partial.

    Builds the LC0 card context via build_lc0_card_context and passes the
    flattened keys plus side_labels to _card_lc0.html.

    Params:
        request (HttpRequest): The incoming HTTP request.
        slug (str): Game slug identifying which game to render.

    Returns:
        HttpResponse: Rendered _card_lc0.html partial with LC0 stats context.
    """
    data = _load_or_404(slug)
    ctx = build_lc0_card_context(data)
    ctx["side_labels"] = [("white", data.white), ("black", data.black)]
    ctx["data"] = data
    return render(request, "games/partials/_card_lc0.html", ctx)


def chips_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the move-category chip row partial for a given ply.

    Assembles up to three chips via chip_data.chips_for_ply: SF classification,
    LC0 base severity, and (when populated) LC0 draw character.  The partial is
    swapped in by HTMX on ``ply-change`` events and on initial page load.

    Params:
        request (HttpRequest): GET request; reads ``?ply=<int>`` (default 0).
        slug (str): Game URL slug.

    Returns:
        Rendered _move_chips.html with ``chips`` context list.
    """
    data = _load_or_404(slug)
    ply = int(request.GET.get("ply", 0) or 0)
    return render(request, "games/partials/_move_chips.html", {
        "chips": chips_for_ply(data, ply),
    })


def chart_winpct_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the Win% headline chart partial.

    Builds the winpct payload (SF Lichess logistic + LC0 wdl_mu*100) and passes
    it as ``payload`` to the template for embedding via json_script.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered _chart_winpct.html partial with serialized winpct data.
    """
    data = _load_or_404(slug)
    return render(request, "games/partials/_chart_winpct.html", {
        "payload": winpct_payload(data),
    })


def chart_sf_cp_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the Stockfish cp-bar chart partial.

    Builds the sf_cp payload (per-move cp_eval + mate_in + classification) and
    passes it as ``payload`` to the template for embedding via json_script.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered _chart_sf_cp.html partial with serialized sf_cp data.
    """
    data = _load_or_404(slug)
    return render(request, "games/partials/_chart_sf_cp.html", {
        "payload": sf_cp_payload(data),
    })


def chart_lc0_wdl_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the LC0 WDL chart partial.

    Builds the lc0_wdl payload (per-move wdl_win_adj/wdl_draw_adj/wdl_loss_adj
    exposed as wdl_win/wdl_draw/wdl_loss) and passes it as ``payload`` to the
    template for embedding via json_script. Also passes network name, draw rate
    reference, and player names for the subtitle and trace labels.

    Params:
        request (HttpRequest): The HTTP request.
        slug (str): Game URL slug.

    Returns:
        Rendered _chart_lc0_wdl.html partial with serialized WDL data.
    """
    data = _load_or_404(slug)
    return render(request, "games/partials/_chart_lc0_wdl.html", {
        "payload": lc0_wdl_payload(data),
        "network_name": data.lc0_network_name,
        "draw_rate_reference": data.lc0_draw_rate_reference,
        "white": data.white,
        "black": data.black,
    })


def pgn_partial(request: HttpRequest, slug: str) -> HttpResponse:
    """Render the PGN table partial.

    Walks the PGN mainline to produce a per-ply move list, attaching SF
    classification from the new-schema MoveAnalysis rows keyed by ply.

    Params:
        request: The incoming HTTP request.
        slug: The game slug identifying which game to render.

    Returns:
        HttpResponse: Rendered _pgn_table.html with ``pgn_moves`` context — a list
        of dicts with keys: ply, san, color ("white"/"black"), move_number, classification.
    """
    data = _load_or_404(slug)
    by_ply_class = {m.ply: m.classification for m in data.sf_moves}
    moves: list[dict] = []
    pgn_game = _pgn.read_game(_io.StringIO(data.pgn))
    board = pgn_game.board()
    start = board.ply()
    for i, mv in enumerate(pgn_game.mainline_moves(), start=1):
        san = board.san(mv)
        board.push(mv)
        ply = i + start
        moves.append({
            "ply": ply,
            "san": san,
            "color": "white" if ply % 2 == 1 else "black",
            "move_number": (ply + 1) // 2,
            "classification": by_ply_class.get(ply),
        })
    return render(request, "games/partials/_pgn_table.html", {"pgn_moves": moves})
