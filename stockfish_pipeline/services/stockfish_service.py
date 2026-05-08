"""
Title: stockfish_service.py — Stockfish game analysis service
Description:
    Analyses chess games using Stockfish via python-chess chess.engine.
    Produces per-move centipawn loss, accuracy, move classification, and
    top-3 multipv candidate continuations (UCI arrows + full SAN sequences).
    Exposes analyze_pgn() for raw PGN strings and analyze_game() for
    pre-parsed chess.pgn.Game objects.

Changelog:
    2026-05-05 (#1): Extract and persist full PV continuations for all 3 multipv lines
"""

from __future__ import annotations

import io
import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess
import chess.engine
import chess.pgn

from stockfish_pipeline.config import get_settings

# Classification thresholds (centipawn loss from mover's perspective)
# Matches Lichess: https://lichess.org/page/accuracy
_BLUNDER_CPL = 300
_MISTAKE_CPL = 100
_INACCURACY_CPL = 50

# Brilliant/great move detection thresholds
# Brilliant: sacrifices material, move is best (CPL < 10), and position was not already clearly winning
# Great: only-good-move in a difficult position (narrow margin, CPL < 10 but alternatives are bad)
_BRILLIANT_MAX_CPL = 10  # must be (near-)best to earn !!
_BRILLIANT_WIN_CEIL = (
    70.0  # don't award !! when already clearly winning (>70% win chance)
)
_BRILLIANT_ALT_FLOOR = 150.0  # second-best alternative must be ≥150 cp worse to qualify
_GREAT_MAX_CPL = 10  # must be (near-)best for !
_GREAT_ALT_FLOOR = 80.0  # only-good-move: alternatives ≥80 cp worse


@dataclass
class MoveResult:
    ply: int
    san: str
    fen: str
    cp_eval: float  # eval after the move was played (white-relative, centipawns)
    best_move: str  # UCI of the engine's top choice before this move
    arrow_uci: str  # same as best_move (consumed by the board UI)
    arrow_uci_2: str  # 2nd-best candidate move UCI (empty string if unavailable)
    arrow_uci_3: str  # 3rd-best candidate move UCI (empty string if unavailable)
    arrow_score_1: float | None = None  # mover-perspective score for best candidate
    arrow_score_2: float | None = None  # mover-perspective score for 2nd candidate
    arrow_score_3: float | None = None  # mover-perspective score for 3rd candidate
    pv_san_1: list[str] = field(default_factory=list)  # full SAN continuation for line 1
    pv_san_2: list[str] = field(default_factory=list)  # full SAN continuation for line 2
    pv_san_3: list[str] = field(default_factory=list)  # full SAN continuation for line 3
    cpl: float = 0.0  # centipawn loss for the side that just moved (≥ 0)
    classification: str = "best"  # brilliant / great / best / excellent / good / inaccuracy / mistake / blunder


@dataclass
class PlayerStats:
    accuracy: float
    acpl: float
    blunders: int
    mistakes: int
    inaccuracies: int


@dataclass
class GameResult:
    white_stats: PlayerStats
    black_stats: PlayerStats
    moves: list[MoveResult]
    engine_depth: int
    analyzed_at: datetime


def _cp(score: chess.engine.Score) -> float:
    """Convert a python-chess Score to white-relative centipawns, preserving mate distance.

    Parameters:
        score: a chess.engine.Score from a multipv info entry.

    Returns:
        Float centipawn value from White's perspective. Mate-in-N is encoded as
        ±10000 so downstream arithmetic stays finite.
    """
    if score.is_mate():
        encoded = score.score(mate_score=10000)
        if encoded is not None:
            return float(encoded)
        mate = score.mate()
        return 10000.0 if (mate is not None and mate > 0) else -10000.0
    val = score.score()
    return float(val) if val is not None else 0.0


def _win_percent(cp: float) -> float:
    """Win percentage (0–100) from a subjective centipawn eval.

    Uses the Lichess empirical sigmoid derived from 2300+ rated games.
    See https://github.com/lichess-org/lila/pull/11148
    """
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def _move_accuracy(wp_before: float, wp_after: float) -> float:
    """Per-move accuracy from Win% before and after (both on 0–100 scale).

    Lichess formula with +1 uncertainty bonus for imperfect analysis depth.
    See https://lichess.org/page/accuracy
    """
    if wp_after >= wp_before:
        return 100.0
    win_diff = wp_before - wp_after
    raw = (
        103.1668100711649 * math.exp(-0.04354415386753951 * win_diff)
        - 3.166924740191411
        + 1
    )
    return max(0.0, min(100.0, raw))


def _harmonic_mean(values: list[float]) -> float:
    """Compute the harmonic mean of a list of floats, safe for near-zero inputs.

    Parameters:
        values: per-move accuracy percentages (0–100).

    Returns:
        Harmonic mean clamped away from zero via a small epsilon; 0.0 for empty input.
    """
    if not values:
        return 0.0
    eps = 0.001
    return len(values) / sum(1.0 / max(v, eps) for v in values)


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    """Compute the weighted arithmetic mean of values.

    Parameters:
        values: per-move accuracy percentages (0–100).
        weights: positional volatility weights, one per value.

    Returns:
        Weighted mean; falls back to simple mean when total weight is zero.
    """
    if not values:
        return 0.0
    total_weight = sum(weights)
    if total_weight == 0:
        return sum(values) / len(values)
    return sum(v * w for v, w in zip(values, weights)) / total_weight


def _game_accuracy(move_accs: list[float], win_percents: list[float]) -> float:
    """Game-level accuracy: (volatility-weighted mean + harmonic mean) / 2.

    Matches Lichess AccuracyPercent.scala — sliding window std-dev weights
    emphasise moves played in volatile positions.
    See https://github.com/lichess-org/lila/blob/master/modules/analyse/src/main/AccuracyPercent.scala
    """
    n = len(move_accs)
    if n == 0:
        return 100.0
    if n == 1:
        return move_accs[0]

    window_size = max(2, min(8, n // 10))

    # Build one weight per move using the std-dev of a sliding window of win%s.
    # Pad the front so every move gets a window of the same logical size.
    weights: list[float] = []
    for i in range(n):
        start = max(0, i - window_size + 1)
        window = win_percents[start : i + 1]
        if len(window) < 2:
            weights.append(0.5)
        else:
            sd = statistics.stdev(window)
            weights.append(max(0.5, min(12.0, sd)))

    harmonic = _harmonic_mean(move_accs)
    weighted = _weighted_mean(move_accs, weights)
    return (harmonic + weighted) / 2.0


def _classify(
    cpl: float,
    wp_before: float,
    wp_after: float,
    best_cp_before: float,
    second_cp_before: float | None,
    is_capture: bool,
) -> str:
    """Classify a move into a quality tier based on CPL and position context.

    Parameters:
        cpl: centipawn loss for the side that moved (≥ 0, mover-relative).
        wp_before: win percentage for the mover before the move (0–100).
        wp_after: win percentage for the mover after the move (0–100).
        best_cp_before: engine's top-line eval before the move (mover-relative cp).
        second_cp_before: engine's second-line eval before the move (mover-relative cp),
            or None when only one legal move exists.
        is_capture: True if the played move captured a piece.

    Returns:
        One of: 'brilliant', 'great', 'best', 'excellent', 'inaccuracy', 'mistake', 'blunder'.

    Classification tiers:
        brilliant (!!): near-best material sacrifice, not already clearly winning.
        great    (!):  only-good-move in a difficult position.
        best:          CPL < 10, neither brilliant nor great.
        excellent:     CPL 10–49.
        inaccuracy:    CPL 50–99.
        mistake:       CPL 100–299.
        blunder:       CPL ≥ 300.
    """
    if cpl >= _BLUNDER_CPL:
        return "blunder"
    if cpl >= _MISTAKE_CPL:
        return "mistake"
    if cpl >= _INACCURACY_CPL:
        return "inaccuracy"

    alt_cpl = (
        (best_cp_before - second_cp_before) if second_cp_before is not None else 0.0
    )

    if (
        cpl < _BRILLIANT_MAX_CPL
        and is_capture
        and wp_before < _BRILLIANT_WIN_CEIL
        and alt_cpl >= _BRILLIANT_ALT_FLOOR
    ):
        return "brilliant"

    if (
        cpl < _GREAT_MAX_CPL
        and second_cp_before is not None
        and alt_cpl >= _GREAT_ALT_FLOOR
    ):
        return "great"

    if cpl < _BRILLIANT_MAX_CPL:
        return "best"
    return "excellent"


def analyze_pgn(
    pgn_text: str,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
    syzygy_path: str | None = None,
    move_callback: Callable[[int, int, str], None] | None = None,
) -> GameResult:
    """Analyze a full game PGN string and return per-move results and player stats.

    Runs Stockfish at multipv=3 for every position once, then pairs pre/post evals
    to compute CPL, accuracy, and classification for each move.

    Parameters:
        pgn_text: raw PGN string for the game to analyze.
        stockfish_path: absolute path to the Stockfish binary.
        depth: analysis depth passed to Stockfish (default 20).
        threads: number of Stockfish search threads (default 1).
        hash_mb: Stockfish hash table size in MB (default 256).
        syzygy_path: optional path to Syzygy endgame tablebases directory.
        move_callback: optional callable invoked after each move is analyzed,
            with signature (ply: int, total_moves: int, san: str) -> None.

    Returns:
        GameResult containing white_stats, black_stats, a MoveResult per ply,
        the engine depth used, and the UTC timestamp of analysis.

    Raises:
        ValueError: if pgn_text cannot be parsed as a valid PGN game.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("Could not parse PGN")

    # Count total moves up front so callers can show a denominator
    total_moves = sum(1 for _ in game.mainline_moves())

    engine_options: dict = {"Threads": str(threads), "Hash": str(hash_mb)}
    if syzygy_path:
        engine_options["SyzygyPath"] = syzygy_path
    limit = chess.engine.Limit(depth=depth)

    move_results: list[MoveResult] = []
    white_move_accs: list[float] = []
    black_move_accs: list[float] = []
    white_cpls: list[float] = []
    black_cpls: list[float] = []
    white_wps: list[float] = []  # mover-relative win% after each white move
    black_wps: list[float] = []  # mover-relative win% after each black move

    # Collect all positions in one pass so we can analyze each board exactly once.
    # Each position's pre-move eval doubles as the previous position's post-move eval.
    # This cuts engine calls from ~3N to N+1 (one multipv=2 call per position, plus
    # one call for the final position to get the last move's post-move eval).
    mainline: list[tuple[chess.Board, chess.Move, str, int]] = []
    _scan_board = game.board()
    for node in game.mainline():
        move = node.move
        ply = _scan_board.ply() + 1
        san = _scan_board.san(move)
        mainline.append((_scan_board.copy(), move, san, ply))
        _scan_board.push(move)
    final_board = _scan_board  # position after the last move

    with chess.engine.SimpleEngine.popen_uci(stockfish_path) as engine:
        engine.configure(engine_options)

        # Analyze every position with multipv=3 to capture the top 3 candidate moves.
        # pos_infos[i] holds a 9-tuple:
        #   (best_cp, second_cp, third_cp,
        #    best_uci, second_uci, third_uci,
        #    pv_san_1, pv_san_2, pv_san_3)
        # for the pre-move board of mainline[i]; pos_infos[N] is the final position.
        # Using multipv=3 throughout eliminates the separate selective multipv=2 pass
        # that was previously needed only for brilliant/great detection.
        def _analyze_board(
            board: chess.Board,
        ) -> tuple[
            float, float | None, float | None,
            str, str, str,
            list[str], list[str], list[str],
        ]:
            """Analyze a single board position with Stockfish at multipv=3.

            Parameters:
                board: the chess.Board position to analyze.

            Returns:
                A 9-tuple of
                (best_cp, second_cp, third_cp,
                 best_uci, second_uci, third_uci,
                 pv_san_1, pv_san_2, pv_san_3)
                where *_cp values are white-relative centipawns, *_uci values are
                the first move of each pv line in UCI notation, and pv_san_* are
                the full move continuations as SAN strings (walked on a board copy
                so the source position is never mutated).
                second_cp and third_cp are None when fewer than 2 or 3 lines exist.
            """
            result = engine.analyse(board, limit, multipv=3)
            entries = result if isinstance(result, list) else [result]

            def _entry(idx: int) -> tuple[float, str, list[str]]:
                """Extract cp, first-move UCI, and full SAN continuation for one pv line.

                Parameters:
                    idx: zero-based index into the multipv entries list.

                Returns:
                    (cp, uci, san_moves) — cp is white-relative centipawns,
                    uci is the first move in UCI notation (empty string if no moves),
                    san_moves is the full continuation as a list of SAN strings.
                    Returns (0.0, "", []) when idx is out of range.
                """
                if idx < len(entries):
                    e = entries[idx]
                    cp = _cp(e["score"].white())
                    pv = e.get("pv", [])
                    uci = pv[0].uci() if pv else ""
                    # Walk the full pv on a temporary board copy to generate SAN
                    # notation — python-chess requires the position to compute SAN.
                    temp_board = board.copy()
                    san_moves: list[str] = []
                    for pv_move in pv:
                        san_moves.append(temp_board.san(pv_move))
                        temp_board.push(pv_move)
                    return cp, uci, san_moves
                return 0.0, "", []

            best_cp, best_uci, pv_san_1 = _entry(0)

            if len(entries) > 1:
                second_cp_val, second_uci, pv_san_2 = _entry(1)
                second_cp: float | None = second_cp_val
            else:
                second_uci, pv_san_2, second_cp = "", [], None

            if len(entries) > 2:
                third_cp_val, third_uci, pv_san_3 = _entry(2)
                third_cp: float | None = third_cp_val
            else:
                third_uci, pv_san_3, third_cp = "", [], None
            return (
                best_cp, second_cp, third_cp,
                best_uci, second_uci, third_uci,
                pv_san_1, pv_san_2, pv_san_3,
            )

        pos_infos: list[
            tuple[
                float, float | None, float | None,
                str, str, str,
                list[str], list[str], list[str],
            ]
        ] = []
        boards_to_analyze = [b for b, _, _, _ in mainline] + [final_board]
        for i, board in enumerate(boards_to_analyze):
            pos_infos.append(_analyze_board(board))
            if move_callback and i < len(mainline):
                _, _, san, ply = mainline[i]
                move_callback(ply, total_moves, san)

        # Pair pre/post evals and build results.
        for idx, (board, move, san, ply) in enumerate(mainline):
            (
                best_cp_before,
                second_cp_before,
                third_cp_before,
                best_move_str,
                second_move_str,
                third_move_str,
                pv_san_1,
                pv_san_2,
                pv_san_3,
            ) = pos_infos[idx]
            after_cp = pos_infos[idx + 1][0]

            is_white_move = board.turn == chess.WHITE
            is_capture = board.is_capture(move)
            legal_moves = list(board.legal_moves)

            board_after = board.copy()
            board_after.push(move)

            score_1 = best_cp_before if is_white_move else -best_cp_before
            score_2 = (
                (second_cp_before if is_white_move else -second_cp_before)
                if second_cp_before is not None
                else None
            )
            score_3 = (
                (third_cp_before if is_white_move else -third_cp_before)
                if third_cp_before is not None
                else None
            )

            if len(legal_moves) == 1:
                move_results.append(
                    MoveResult(
                        ply=ply,
                        san=san,
                        fen=board_after.fen(),
                        cp_eval=after_cp,
                        best_move=move.uci(),
                        arrow_uci=move.uci(),
                        arrow_uci_2=second_move_str,
                        arrow_uci_3=third_move_str,
                        arrow_score_1=score_1,
                        arrow_score_2=score_2,
                        arrow_score_3=score_3,
                        pv_san_1=pv_san_1,
                        pv_san_2=pv_san_2,
                        pv_san_3=pv_san_3,
                        cpl=0.0,
                        classification="best",
                    )
                )
                continue

            if is_white_move:
                cpl = max(0.0, best_cp_before - after_cp)
            else:
                cpl = max(0.0, after_cp - best_cp_before)

            if is_white_move:
                second_cp_mover = second_cp_before
            else:
                second_cp_mover = (
                    -second_cp_before if second_cp_before is not None else None
                )

            wp_before = _win_percent(
                best_cp_before if is_white_move else -best_cp_before
            )
            wp_after = _win_percent(after_cp if is_white_move else -after_cp)
            move_acc = _move_accuracy(wp_before, wp_after)

            best_cp_mover = best_cp_before if is_white_move else -best_cp_before
            classification = _classify(
                cpl=cpl,
                wp_before=wp_before,
                wp_after=wp_after,
                best_cp_before=best_cp_mover,
                second_cp_before=second_cp_mover,
                is_capture=is_capture,
            )

            if is_white_move:
                white_cpls.append(cpl)
                white_move_accs.append(move_acc)
                white_wps.append(wp_after)
            else:
                black_cpls.append(cpl)
                black_move_accs.append(move_acc)
                black_wps.append(wp_after)

            move_results.append(
                MoveResult(
                    ply=ply,
                    san=san,
                    fen=board_after.fen(),
                    cp_eval=after_cp,
                    best_move=best_move_str,
                    arrow_uci=best_move_str,
                    arrow_uci_2=second_move_str,
                    arrow_uci_3=third_move_str,
                    arrow_score_1=score_1,
                    arrow_score_2=score_2,
                    arrow_score_3=score_3,
                    pv_san_1=pv_san_1,
                    pv_san_2=pv_san_2,
                    pv_san_3=pv_san_3,
                    cpl=cpl,
                    classification=classification,
                )
            )

    def _stats(
        cpls: list[float], move_accs: list[float], wps: list[float]
    ) -> PlayerStats:
        """Aggregate per-move data into a PlayerStats summary for one color.

        Parameters:
            cpls: centipawn-loss values for each of the player's moves.
            move_accs: per-move accuracy percentages (0–100).
            wps: win-percentage after each of the player's moves (mover-relative).

        Returns:
            PlayerStats with accuracy, ACPL, and blunder/mistake/inaccuracy counts.
        """
        if not cpls:
            return PlayerStats(
                accuracy=100.0, acpl=0.0, blunders=0, mistakes=0, inaccuracies=0
            )
        return PlayerStats(
            accuracy=_game_accuracy(move_accs, wps),
            acpl=sum(cpls) / len(cpls),
            blunders=sum(1 for c in cpls if c >= _BLUNDER_CPL),
            mistakes=sum(1 for c in cpls if _MISTAKE_CPL <= c < _BLUNDER_CPL),
            inaccuracies=sum(1 for c in cpls if _INACCURACY_CPL <= c < _MISTAKE_CPL),
        )

    return GameResult(
        white_stats=_stats(white_cpls, white_move_accs, white_wps),
        black_stats=_stats(black_cpls, black_move_accs, black_wps),
        moves=move_results,
        engine_depth=depth,
        analyzed_at=datetime.now(timezone.utc),
    )


def analyze_game(
    game: chess.pgn.Game,
    stockfish_path: str,
    depth: int = 20,
    threads: int = 1,
    hash_mb: int = 256,
    syzygy_path: str | None = None,
) -> GameResult:
    """Analyse a pre-parsed chess.pgn.Game object.

    Convenience wrapper around analyze_pgn() for callers that already hold a
    parsed game (e.g. the RunPod serverless handler).

    Returns the same GameResult as analyze_pgn().
    """
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    pgn_text = game.accept(exporter)
    return analyze_pgn(
        pgn_text=pgn_text,
        stockfish_path=stockfish_path,
        depth=depth,
        threads=threads,
        hash_mb=hash_mb,
        syzygy_path=syzygy_path,
    )
