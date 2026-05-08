"""
Title: stat_cards.py — Du Bois-style engine analysis stat card generators
Description:
    Generates HTML stat card fragments for the game analysis page, covering
    Stockfish accuracy/ACPL/move-quality and Lc0 WDL probability cards.
    Includes rerun-analysis buttons with queue-state awareness.

Changelog:
    2026-05-04 (#16): Added queued param to build_sf_card/build_lc0_card;
                      embedded count labels in quality segments; added _rerun_button;
                      separated build_sf_card/build_lc0_card from build_stat_cards_html
"""

from __future__ import annotations

from html import escape
from typing import Optional

from games.services import GameAnalysisData

_DUB_CSS = """<style>
.dub{font-family:'DM Mono','Courier New',monospace;color:#1A1A1A;margin-bottom:1.6rem;}
.dub-head{border-top:3px solid #1A1A1A;border-bottom:1.5px solid #1A1A1A;display:flex;justify-content:space-between;align-items:baseline;padding:5px 0 4px;margin-bottom:16px;}
.dub-title{font-family:'Playfair Display SC','Cormorant Garamond',Georgia,serif;font-size:.92rem;letter-spacing:.07em;color:#1A3A2A;}
.dub-meta{font-size:.60rem;letter-spacing:.06em;color:#8B3A2A;text-transform:uppercase;}
.dub-player-name{font-size:1.0rem;font-weight:700;color:#1A1A1A;margin:12px 0 8px;}
.dub-metric-label{font-size:.65rem;color:#5A5A5A;text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px;}
.dub-chip{display:inline-block;background:#EFE4CC;border:1px solid #1A1A1A;padding:.3rem .6rem;border-radius:3px;font-size:.60rem;margin-right:8px;margin-bottom:6px;}
.dub-row{display:grid;grid-template-columns:1fr 52px;align-items:center;gap:0 8px;margin-bottom:5px;}
.dub-player-lbl{font-size:.70rem;letter-spacing:.03em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#1A1A1A;}
.dub-chess{font-size:1.1em;margin-right:4px;}
.dub-val{font-size:.78rem;font-weight:700;text-align:right;white-space:nowrap;color:#1A1A1A;}
.dub-bar{height:28px;background:#F2E6D0;border:1.5px solid #1A1A1A;position:relative;overflow:hidden;}
.dub-bar-fill{position:absolute;left:0;top:0;bottom:0;height:100%;display:flex;align-items:center;padding-left:6px;}
.dub-bar-lbl{font-size:.65rem;font-weight:700;color:#FFFFFF;white-space:nowrap;overflow:hidden;}
.dub-stack{height:28px;display:flex;border:1.5px solid #1A1A1A;overflow:hidden;}
.dub-seg{display:flex;align-items:center;justify-content:center;font-size:.60rem;font-weight:700;overflow:hidden;white-space:nowrap;color:#F2E6D0;}
.dub-win{background:#1A3A2A;}.dub-draw{background:#8B3A2A;}.dub-loss{background:#B53541;}
.dub-bril{background:#2C6B4A;}.dub-best{background:#4A6E8A;}.dub-great{background:#4A6554;}
.dub-neut{background:#EFE4CC;color:#5A5A5A;}.dub-inac{background:#E07B7B;color:#1A1A1A;}
.dub-mist{background:#CE3A4A;}.dub-blun{background:#B53541;}
.dub-lbl{font-size:.54rem;letter-spacing:.12em;text-transform:uppercase;color:#5A5A5A;margin:10px 0 4px;}
.dub-rule{border:none;border-top:1px solid #D4C4A0;margin:12px 0 10px;}
.dub-legend{display:flex;gap:8px;flex-wrap:wrap;font-size:.57rem;color:#5A5A5A;letter-spacing:.04em;margin-top:5px;}
.dub-swatch{display:inline-block;width:9px;height:9px;border:1px solid #1A1A1A;vertical-align:middle;margin-right:2px;}
.wc-btn{display:inline-block;font-family:'DM Mono',monospace;font-size:.72rem;letter-spacing:.06em;border:1.5px solid #1A1A1A;padding:.3rem .7rem;cursor:pointer;background:transparent;color:#1A1A1A;text-decoration:none;transition:background .15s,color .15s;}
.wc-btn:hover{background:#1A1A1A;color:#F2E6D0;}
.wc-btn:disabled{opacity:.45;cursor:not-allowed;}
.wc-btn-sm{font-size:.65rem;padding:.2rem .5rem;}
.wc-btn-ghost{border-color:#5A5A5A;color:#5A5A5A;}
.wc-btn-ghost:hover{background:#5A5A5A;color:#F2E6D0;}
</style>"""

_QUALITY_INLINE_LEGEND = (
    '<div class="dub-legend">'
    '<span><span class="dub-swatch" style="background:#2C6B4A"></span>!! Brilliant</span>'
    '<span><span class="dub-swatch" style="background:#4A6E8A"></span>B Best</span>'
    '<span><span class="dub-swatch" style="background:#4A6554"></span>Gr Great</span>'
    '<span><span class="dub-swatch" style="background:#EFE4CC"></span>Good</span>'
    '<span><span class="dub-swatch" style="background:#E07B7B"></span>?! Inaccuracy</span>'
    '<span><span class="dub-swatch" style="background:#CE3A4A"></span>? Mistake</span>'
    '<span><span class="dub-swatch" style="background:#B53541"></span>?? Blunder</span>'
    "</div>"
)


def _acc_color(pct: float) -> str:
    """
    Return a hex color code appropriate for an accuracy percentage.

    Params:
        pct (float): Accuracy percentage 0–100.

    Returns:
        Hex color string.
    """
    if pct >= 90:
        return "#1A3A2A"
    if pct >= 80:
        return "#4A6554"
    if pct >= 70:
        return "#D4A843"
    return "#B53541"


def _bar_row(sym: str, name: str, pct: float, val_str: str, fill: str | None = None, is_winner: bool = False) -> str:
    """
    Generate HTML for a single stat bar row with player label, filled bar, and value.

    Params:
        sym (str): Chess piece symbol (♙ or ♟).
        name (str): Player name.
        pct (float): Bar fill percentage 0–100.
        val_str (str): Display value string shown in the right column.
        fill (str | None): Custom hex color for the bar fill; defaults to accuracy color.
        is_winner (bool): Whether this player won the game.

    Returns:
        HTML string for the row.
    """
    color = fill or _acc_color(pct)
    w = min(max(pct, 0), 100)
    inner_lbl = f'<span class="dub-bar-lbl">{escape(val_str)}</span>' if w > 15 else ""
    
    # Determine piece color based on piece symbol
    piece_color = "#FFFFFF" if sym == "♙" else "#000000"
    trophy = " 🏆" if is_winner else ""
    
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess" style="color:{piece_color}">{sym}</span>{escape(name)}{trophy}</div>'
        f'<div class="dub-bar"><div class="dub-bar-fill" style="width:{w:.1f}%;background:{color}">{inner_lbl}</div></div>'
        f'<div class="dub-val">{escape(val_str)}</div>'
        f"</div>"
    )


def _metric_bar(pct: float, val_str: str, fill: str | None = None) -> str:
    """
    Generate HTML for a metric bar row without player label.

    Params:
        pct (float): Bar fill percentage 0–100.
        val_str (str): Display value string shown in the right column.
        fill (str | None): Custom hex color for the bar fill; defaults to accuracy color.

    Returns:
        HTML string for the row.
    """
    color = fill or _acc_color(pct)
    w = min(max(pct, 0), 100)
    inner_lbl = f'<span class="dub-bar-lbl">{escape(val_str)}</span>' if w > 15 else ""
    
    return (
        f'<div class="dub-row">'
        f'<div class="dub-bar" title="Percentage of moves matching engine recommendation or within margin of best move"><div class="dub-bar-fill" style="width:{w:.1f}%;background:{color}">{inner_lbl}</div></div>'
        f"</div>"
    )


def _quality_metric_bar(brilliant: int, best: int, great: int, inaccuracy: int, mistake: int, blunder: int, total: int) -> str:
    """
    Generate HTML for move quality classification bar row without player label.

    Params:
        brilliant (int): Count of brilliant moves.
        best (int): Count of best moves.
        great (int): Count of great moves.
        inaccuracy (int): Count of inaccuracies.
        mistake (int): Count of mistakes.
        blunder (int): Count of blunders.
        total (int): Total moves.

    Returns:
        HTML string for the row.
    """
    classified = brilliant + best + great + inaccuracy + mistake + blunder
    neutral = max(0, total - classified)

    def _seg(cls: str, n: int, short_lbl: str) -> str:
        """Build a single quality classification segment."""
        if n == 0 or total == 0:
            return ""
        pct = n / total * 100
        txt = f"{short_lbl} {n}" if pct >= 6 else ""
        tooltip = ""
        if "!!" in short_lbl:
            tooltip = f"Brilliant moves: excellent moves that significantly improved position ({n})"
        elif "!" in short_lbl and "?" not in short_lbl:
            tooltip = f"Best moves: engine-recommended best moves ({n})"
        elif "!?" in short_lbl:
            tooltip = f"Great moves: very good moves slightly worse than best ({n})"
        elif "?!" in short_lbl:
            tooltip = f"Inaccuracies: suboptimal moves with small drawback ({n})"
        elif short_lbl == "?":
            tooltip = f"Mistakes: poor moves with significant drawback ({n})"
        elif short_lbl == "??":
            tooltip = f"Blunders: terrible moves with major material or positional loss ({n})"
        return f'<div class="dub-seg {cls}" style="flex:{pct:.2f}" title="{tooltip}">{escape(txt)}</div>'

    neu_seg = ""
    if neutral > 0 and total > 0:
        pct = neutral / total * 100
        neu_seg = f'<div class="dub-seg dub-neut" style="flex:{pct:.2f}" title="Unclassified moves: not classified by engine or below threshold ({neutral})"></div>'

    segs = (
        _seg("dub-bril", brilliant, "!!")
        + _seg("dub-best", best, "!")
        + _seg("dub-great", great, "!?")
        + neu_seg
        + _seg("dub-inac", inaccuracy, "?!")
        + _seg("dub-mist", mistake, "?")
        + _seg("dub-blun", blunder, "??")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-stack" title="Distribution of move quality classifications across all moves">{segs}</div>'
        f"</div>"
    )


def _wdl_row(sym: str, name: str, win: float, draw: float, loss: float, is_winner: bool = False) -> str:
    """
    Generate HTML for a Win/Draw/Loss probability stacked bar row.

    Params:
        sym (str): Chess piece symbol.
        name (str): Player name.
        win (float): Win probability 0–100.
        draw (float): Draw probability 0–100.
        loss (float): Loss probability 0–100.
        is_winner (bool): Whether this player won the game.

    Returns:
        HTML string for the row.
    """
    def _seg(cls: str, pct: float, lbl: str) -> str:
        """Build a single WDL segment."""
        txt = lbl if pct >= 9 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.1f}">{escape(txt)}</div>'

    piece_color = "#FFFFFF" if sym == "♙" else "#000000"
    trophy = " 🏆" if is_winner else ""
    
    segs = (
        _seg("dub-win", win, f"W {win:.0f}%")
        + _seg("dub-draw", draw, f"D {draw:.0f}%")
        + _seg("dub-loss", loss, f"L {loss:.0f}%")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess" style="color:{piece_color}">{sym}</span>{escape(name)}{trophy}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:.58rem;color:#5A5A5A">WDL</div>'
        f"</div>"
    )


def _wdl_bar(win: float, draw: float, loss: float) -> str:
    """
    Generate HTML for a WDL bar row without player label.

    Params:
        win (float): Win probability 0–100.
        draw (float): Draw probability 0–100.
        loss (float): Loss probability 0–100.

    Returns:
        HTML string for the row.
    """
    def _seg(cls: str, pct: float, lbl: str) -> str:
        """Build a single WDL segment."""
        txt = lbl if pct >= 9 else ""
        tooltip = ""
        if "W" in lbl:
            tooltip = f"Probability of winning from this position"
        elif "D" in lbl:
            tooltip = f"Probability of drawing from this position"
        elif "L" in lbl:
            tooltip = f"Probability of losing from this position"
        return f'<div class="dub-seg {cls}" style="flex:{pct:.1f}" title="{tooltip}">{escape(txt)}</div>'

    segs = (
        _seg("dub-win", win, f"W {win:.0f}%")
        + _seg("dub-draw", draw, f"D {draw:.0f}%")
        + _seg("dub-loss", loss, f"L {loss:.0f}%")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-stack" title="Probability distribution: Win, Draw, Loss">{segs}</div>'
        f"</div>"
    )


def _quality_row(
    sym: str, name: str,
    brilliant: int, best: int, great: int,
    inaccuracy: int, mistake: int, blunder: int,
    total: int,
    is_winner: bool = False,
) -> str:
    """
    Generate HTML for a move quality classification stacked bar row.

    Each segment shows a chess annotation symbol (e.g., "!! 2") when wide enough.

    Params:
        sym (str): Chess piece symbol.
        name (str): Player name.
        brilliant (int): Count of brilliant moves.
        best (int): Count of best moves.
        great (int): Count of great moves.
        inaccuracy (int): Count of inaccuracies.
        mistake (int): Count of mistakes.
        blunder (int): Count of blunders.
        total (int): Total moves for this side.
        is_winner (bool): Whether this player won the game.

    Returns:
        HTML string for the row.
    """
    classified = brilliant + best + great + inaccuracy + mistake + blunder
    neutral = max(0, total - classified)

    def _seg(cls: str, n: int, short_lbl: str) -> str:
        """Build a single quality classification segment."""
        if n == 0 or total == 0:
            return ""
        pct = n / total * 100
        txt = f"{short_lbl} {n}" if pct >= 6 else ""
        return f'<div class="dub-seg {cls}" style="flex:{pct:.2f}">{escape(txt)}</div>'

    neu_seg = ""
    if neutral > 0 and total > 0:
        pct = neutral / total * 100
        neu_seg = f'<div class="dub-seg dub-neut" style="flex:{pct:.2f}"></div>'

    piece_color = "#FFFFFF" if sym == "♙" else "#000000"
    trophy = " 🏆" if is_winner else ""

    segs = (
        _seg("dub-bril", brilliant, "!!")
        + _seg("dub-best", best, "!")
        + _seg("dub-great", great, "!?")
        + neu_seg
        + _seg("dub-inac", inaccuracy, "?!")
        + _seg("dub-mist", mistake, "?")
        + _seg("dub-blun", blunder, "??")
    )
    return (
        f'<div class="dub-row">'
        f'<div class="dub-player-lbl"><span class="dub-chess" style="color:{piece_color}">{sym}</span>{escape(name)}{trophy}</div>'
        f'<div class="dub-stack">{segs}</div>'
        f'<div class="dub-val" style="font-size:.60rem;color:#5A5A5A">{total}</div>'
        f"</div>"
    )


def _rerun_button(engine: str, queued: bool, in_header: bool = False) -> str:
    """
    Generate an HTML rerun-analysis button for an engine card.

    When queued=True the button is disabled. Otherwise it opens the confirmation
    modal via window.openQueueModal().

    Params:
        engine (str): Engine identifier — "stockfish" or "lc0".
        queued (bool): Whether this engine already has an active job.
        in_header (bool): Whether the button is in the header (no margin-top).

    Returns:
        HTML button string.
    """
    label = "Stockfish" if engine == "stockfish" else "Lc0"
    btn_id = f"queue-btn-{engine}"
    margin_style = "" if in_header else "margin-top:10px;"
    if queued:
        return (
            f'<button id="{btn_id}" class="wc-btn wc-btn-sm" disabled '
            f'style="{margin_style}">Already Queued</button>'
        )
    return (
        f'<button id="{btn_id}" class="wc-btn wc-btn-sm" '
        f'onclick="window.openQueueModal(\'{engine}\')" '
        f'style="{margin_style}">Re-run {label}</button>'
    )


def build_sf_card(data: GameAnalysisData, queued: bool = False) -> str:
    """
    Generate Stockfish analysis stat card HTML.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        queued (bool): Whether a Stockfish job is currently active in the queue.

    Returns:
        HTML string for the card, or empty string if no SF data.
    """
    if not data.has_sf:
        return ""

    meta_parts = []
    if data.engine_depth:
        meta_parts.append(f"depth {data.engine_depth}")
    meta = " · ".join(meta_parts)

    # Determine who won
    white_won = data.result == "1-0"
    black_won = data.result == "0-1"

    # Build content organized by player
    content = ""
    
    for sym, name, has_acc, acc_val, has_acpl, acpl_val, side_moves, blun, mist, inac, is_winner in [
        ("♙", data.white, data.white_accuracy is not None, data.white_accuracy, 
         data.white_acpl is not None, data.white_acpl,
         [m for m in data.moves if m.ply % 2 == 1], 
         data.white_blunders, data.white_mistakes, data.white_inaccuracies, white_won),
        ("♟", data.black, data.black_accuracy is not None, data.black_accuracy, 
         data.black_acpl is not None, data.black_acpl,
         [m for m in data.moves if m.ply % 2 == 0], 
         data.black_blunders, data.black_mistakes, data.black_inaccuracies, black_won),
    ]:
        # Add player section if we have any data
        if has_acc or any(m.classification for m in side_moves):
            # Player name label (bigger)
            content += f'<div class="dub-player-name">{escape(name)}{" 🏆" if is_winner else ""}</div>'
            
            # Accuracy bar with label
            if has_acc:
                content += f'<div class="dub-metric-label" title="Percentage of moves that match the engine\'s top choice or were within 50 centipawns of the best move">Accuracy</div>'
                content += _metric_bar(acc_val, f"{acc_val:.1f}%")
            
            # Move quality bar with label
            if side_moves and any(m.classification for m in side_moves):
                def _cnt(moves_list, cls):
                    return sum(1 for m in moves_list if m.classification == cls)
                
                bril = _cnt(side_moves, "brilliant")
                best = _cnt(side_moves, "best")
                great = _cnt(side_moves, "great")
                inaccuracy = inac if inac is not None else _cnt(side_moves, "inaccuracy")
                mistake = mist if mist is not None else _cnt(side_moves, "mistake")
                blunder = blun if blun is not None else _cnt(side_moves, "blunder")
                total = len(side_moves)
                if total:
                    content += f'<div class="dub-metric-label" title="Classification of each move: !! (brilliant), ! (best), !? (great), ?! (inaccuracy), ? (mistake), ?? (blunder)">Move Quality</div>'
                    content += _quality_metric_bar(bril, best, great, inaccuracy, mistake, blunder, total)
            
            # ACPL chip if available (at bottom)
            if has_acpl and acpl_val is not None:
                content += f'<div class="dub-chip" style="margin-top:8px;" title="Average Centipawn Loss: the average difference between your moves and the engine\'s best move, measured in centipawns (1/100th of a pawn). Lower is better.">ACPL: {acpl_val:.1f}</div>'
            
            # Add spacing between players
            if name == data.white:
                content += '<hr class="dub-rule">'

    # Add rerun button row below players
    button_row = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">'
        + _rerun_button("stockfish", queued, in_header=False)
        + f'</div>'
    )

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Stockfish Analysis</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f"</div>"
        + content
        + button_row
        + "</div>"
    )


def build_lc0_card(data: GameAnalysisData, queued: bool = False) -> str:
    """
    Generate Lc0 neural network analysis stat card HTML.

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        queued (bool): Whether an Lc0 job is currently active in the queue.

    Returns:
        HTML string for the card, or empty string if no Lc0 data.
    """
    if not data.has_lc0:
        return ""
    if data.lc0_white_win_prob is None and data.lc0_black_win_prob is None:
        return ""

    meta_parts = []
    if data.lc0_network_name:
        meta_parts.append(data.lc0_network_name)
    if data.lc0_engine_nodes:
        meta_parts.append(f"{data.lc0_engine_nodes:,} nodes/move")
    meta = " · ".join(meta_parts)

    # Determine who won
    white_won = data.result == "1-0"
    black_won = data.result == "0-1"

    # Build content organized by player
    content = ""
    
    for sym, name, win_prob, draw_prob, loss_prob, inac, mist, blun, is_winner in [
        ("♙", data.white, data.lc0_white_win_prob, data.lc0_white_draw_prob or 0.0, data.lc0_white_loss_prob or 0.0,
         data.lc0_white_inaccuracies, data.lc0_white_mistakes, data.lc0_white_blunders, white_won),
        ("♟", data.black, data.lc0_black_win_prob, data.lc0_black_draw_prob or 0.0, data.lc0_black_loss_prob or 0.0,
         data.lc0_black_inaccuracies, data.lc0_black_mistakes, data.lc0_black_blunders, black_won),
    ]:
        # Only render if we have WDL data
        if win_prob is not None:
            # Player name label
            content += f'<div class="dub-player-name">{escape(name)}{" 🏆" if is_winner else ""}</div>'
            
            # Win/Draw/Loss bar with label and tooltip
            content += f'<div class="dub-metric-label" title="Probability of winning, drawing, or losing from the average position during the game">Win / Draw / Loss</div>'
            content += _wdl_bar(win_prob, draw_prob, loss_prob)
            
            # Move quality bar if we have LC0 moves with classifications
            if data.lc0_moves:
                side_moves = [m for m in data.lc0_moves if (name == data.white and m.ply % 2 == 1) or (name == data.black and m.ply % 2 == 0)]
                if side_moves and any(m.classification for m in side_moves):
                    def _cnt(moves_list, cls):
                        return sum(1 for m in moves_list if m.classification == cls)
                    
                    bril = _cnt(side_moves, "brilliant")
                    best = _cnt(side_moves, "best")
                    great = _cnt(side_moves, "great")
                    inaccuracy_lc0 = _cnt(side_moves, "inaccuracy")
                    mistake_lc0 = _cnt(side_moves, "mistake")
                    blunder_lc0 = _cnt(side_moves, "blunder")
                    total = len(side_moves)
                    if total:
                        content += f'<div class="dub-metric-label" title="Classification of each move: !! (brilliant), ! (best), !? (great), ?! (inaccuracy), ? (mistake), ?? (blunder)">Move Quality</div>'
                        content += _quality_metric_bar(bril, best, great, inaccuracy_lc0, mistake_lc0, blunder_lc0, total)
                    
                    # Average Move Win Delta chip
                    valid_deltas = [m.move_win_delta for m in side_moves if m.move_win_delta is not None]
                    if valid_deltas:
                        avg_delta = sum(valid_deltas) / len(valid_deltas)
                        content += f'<div class="dub-chip" style="margin-top:8px;" title="Average change in win probability per move. Lower is better (moves that maintained/improved winning chances).">Avg Δ: {avg_delta:.1f}</div>'
            
            # Add spacing between players
            if name == data.white:
                content += '<hr class="dub-rule">'

    # Add rerun button row below players
    button_row = (
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">'
        + _rerun_button("lc0", queued, in_header=False)
        + f'</div>'
    )

    return (
        f'<div class="dub">'
        f'<div class="dub-head">'
        f'<span class="dub-title">Lc0 Neural Network</span>'
        f'<span class="dub-meta">{escape(meta)}</span>'
        f"</div>"
        + content
        + button_row
        + "</div>"
    )


def build_stat_cards_html(data: GameAnalysisData, sf_queued: bool = False, lc0_queued: bool = False) -> str:
    """
    Return the full Du Bois stat cards HTML block (CSS + SF card + Lc0 card).

    Params:
        data (GameAnalysisData): Assembled game analysis data.
        sf_queued (bool): Whether a Stockfish job is currently active.
        lc0_queued (bool): Whether an Lc0 job is currently active.

    Returns:
        Complete HTML block with inline CSS and both engine cards.
    """
    cards = build_sf_card(data, queued=sf_queued) + build_lc0_card(data, queued=lc0_queued)
    if not cards:
        return '<p class="font-mono text-sm text-slate">No engine analysis available yet.</p>'
    return _DUB_CSS + cards
