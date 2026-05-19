"""
Title: recompute_lc0_calibration.py — Offline recompute of Lc0 WDL calibration fields
Description:
    Pure-DB management command that recomputes all derived Lc0MoveAnalysis
    fields (wdl_*_adj, wdl_mu, delta_mu, delta_d, base_severity,
    draw_character) from the stored raw WDL triples and per-game calibration
    metadata (draw_rate_reference, wdl_calibration_elo, contempt).  No lc0
    engine is launched; the command is safe to run on the app server.

    white_elo and black_elo are recovered from stored game fields:
        white_elo = wdl_calibration_elo
        black_elo = wdl_calibration_elo - contempt

    For ply 1 the pre-move evaluation is unavailable (no prior position is
    stored), so delta_mu and delta_d are set to 0 and the move is classified
    via classify_draw_aware(0, 0) which yields "Best".  For all subsequent
    plies the pre-move raw WDL is the stored raw triple of the preceding ply.

    After updating move-level fields the command also recomputes the per-side
    blunder/mistake/inaccuracy counters and the per-side average WDL
    probabilities on Lc0GameAnalysis and saves them in the same transaction.

Changelog:
    2026-05-19 (#159/E1): Initial creation.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analysis.models import Lc0GameAnalysis
from analysis.wdl_calibration import classify_draw_aware, rescale_wdl

log = logging.getLogger(__name__)

# Fields written back to each Lc0MoveAnalysis row.
_MOVE_UPDATE_FIELDS = [
    "wdl_win_adj",
    "wdl_draw_adj",
    "wdl_loss_adj",
    "wdl_mu",
    "delta_mu",
    "delta_d",
    "base_severity",
    "draw_character",
]

# Fields written back to each Lc0GameAnalysis row after tallying moves.
_GAME_UPDATE_FIELDS = [
    "white_win_prob",
    "white_draw_prob",
    "white_loss_prob",
    "black_win_prob",
    "black_draw_prob",
    "black_loss_prob",
    "white_blunders",
    "white_mistakes",
    "white_inaccuracies",
    "black_blunders",
    "black_mistakes",
    "black_inaccuracies",
]

_COUNTER_FIELD = {"blunders": "blunders", "mistakes": "mistakes", "inaccuracies": "inaccuracies"}


def _recover_elos(game_analysis: Lc0GameAnalysis) -> tuple[int, int]:
    """Derive white_elo and black_elo from stored calibration metadata.

    The worker stores white_elo as wdl_calibration_elo and the signed gap
    (white_elo - black_elo) as contempt, so black_elo = wdl_calibration_elo - contempt.

    Args:
        game_analysis: The Lc0GameAnalysis row to recover Elos from.

    Returns:
        (white_elo, black_elo) as integers.

    Raises:
        ValueError: if wdl_calibration_elo or contempt is None (cannot recover).
    """
    if game_analysis.wdl_calibration_elo is None or game_analysis.contempt is None:
        raise ValueError(
            f"Lc0GameAnalysis {game_analysis.pk}: wdl_calibration_elo or contempt "
            "is None — cannot recover white_elo / black_elo"
        )
    white_elo = int(game_analysis.wdl_calibration_elo)
    black_elo = white_elo - int(game_analysis.contempt)
    return white_elo, black_elo


def _rescale_one_move(
    raw_white: tuple[int, int, int],
    white_elo: int,
    black_elo: int,
    white_to_move: bool,
    draw_rate_reference: float,
) -> tuple[tuple[int, int, int], float]:
    """Apply rescale_wdl and return (adj_triple, mu_white_frame).

    mu_white_frame is the expected-score fraction (W + 0.5D) / total from the
    rescaled triple in White's frame (a probability in [0, 1]).

    Args:
        raw_white: (win, draw, loss) raw permille, White frame.
        white_elo: White player Elo.
        black_elo: Black player Elo.
        white_to_move: True when it is White's turn at this position.
        draw_rate_reference: Per-network reference draw rate.

    Returns:
        (adj_triple, mu_white_frame) where adj_triple is (win, draw, loss)
        permille in White's frame post-rescale.
    """
    result = rescale_wdl(
        *raw_white,
        white_elo=float(white_elo),
        black_elo=float(black_elo),
        white_to_move=white_to_move,
        draw_rate_reference=draw_rate_reference,
    )
    adj = result.wdl_white
    total = adj[0] + adj[1] + adj[2] or 1
    mu_white_frame = (adj[0] + 0.5 * adj[1]) / total
    return adj, mu_white_frame


def _classify_one_move(
    raw_after: tuple[int, int, int],
    raw_before: Optional[tuple[int, int, int]],
    white_elo: int,
    black_elo: int,
    white_to_move: bool,
    draw_rate_reference: float,
) -> tuple[tuple[int, int, int], Optional[float], Optional[float], Optional[float], str, Optional[str]]:
    """Rescale and classify a single move.

    When raw_before is None (first ply — no prior position stored), delta_mu
    and delta_d are both 0 and the move is classified as if no winning chances
    were lost.

    Args:
        raw_after: Raw (win, draw, loss) permille, White frame, after this move.
        raw_before: Raw (win, draw, loss) permille, White frame, before this move.
            None for the first move (ply 1).
        white_elo: White player Elo.
        black_elo: Black player Elo.
        white_to_move: True when it is White's turn (the mover is White).
        draw_rate_reference: Per-network reference draw rate.

    Returns:
        Tuple of (adj_triple, wdl_mu, delta_mu, delta_d, base_severity,
        draw_character).
    """
    adj_after, mu_after_white = _rescale_one_move(
        raw_after, white_elo, black_elo, white_to_move, draw_rate_reference,
    )

    if raw_before is not None:
        adj_before, mu_before_white = _rescale_one_move(
            raw_before, white_elo, black_elo, white_to_move, draw_rate_reference,
        )
        # Convert to mover frame: flip for Black
        if white_to_move:
            mu_before_mover = mu_before_white
            mu_after_mover = mu_after_white
        else:
            mu_before_mover = 1.0 - mu_before_white
            mu_after_mover = 1.0 - mu_after_white

        d_mu = max(0.0, mu_before_mover - mu_after_mover)
        d_before = adj_before[1] / (sum(adj_before) or 1)
        d_after = adj_after[1] / (sum(adj_after) or 1)
        d_d = d_after - d_before
    else:
        # First ply: no prior position to compute a delta against
        if white_to_move:
            mu_after_mover = mu_after_white
        else:
            mu_after_mover = 1.0 - mu_after_white
        d_mu = 0.0
        d_d = 0.0

    cls = classify_draw_aware(d_mu, d_d)
    return adj_after, mu_after_mover, d_mu, d_d, cls.base, cls.modifier


def _avg(values: list[float]) -> Optional[float]:
    """Return the arithmetic mean of a list, or None when the list is empty.

    Args:
        values: List of floats to average.

    Returns:
        Mean as float, or None if values is empty.
    """
    return sum(values) / len(values) if values else None


def _recompute_game(game_analysis: Lc0GameAnalysis) -> None:
    """Recompute all derived move fields for one Lc0GameAnalysis, in a transaction.

    Iterates moves in ply order, applies rescale_wdl + classify_draw_aware,
    writes back move fields, then recomputes per-side counters and average WDL
    probabilities on the parent Lc0GameAnalysis row.

    Args:
        game_analysis: The Lc0GameAnalysis to recompute.

    Side effects:
        Saves updated Lc0MoveAnalysis rows and the parent Lc0GameAnalysis row.
        All writes occur inside a single transaction.atomic() block.
    """
    draw_rate_reference = game_analysis.draw_rate_reference
    if not draw_rate_reference:
        log.info(
            "recompute_lc0_calibration: skipping game_analysis %d — "
            "draw_rate_reference is missing",
            game_analysis.pk,
        )
        return

    white_elo, black_elo = _recover_elos(game_analysis)

    moves = list(
        game_analysis.moves.order_by("ply").only(
            "id", "ply", "wdl_win", "wdl_draw", "wdl_loss",
        )
    )

    if not moves:
        log.info(
            "recompute_lc0_calibration: game_analysis %d has no moves — skipping",
            game_analysis.pk,
        )
        return

    # Per-side accumulators (mirror analyze_pgn / _build_game_result)
    white_wins: list[float] = []
    white_draws: list[float] = []
    white_losses: list[float] = []
    black_wins: list[float] = []
    black_draws: list[float] = []
    black_losses: list[float] = []
    cls_counts: dict[str, dict[str, int]] = {
        "white": {"blunders": 0, "mistakes": 0, "inaccuracies": 0},
        "black": {"blunders": 0, "mistakes": 0, "inaccuracies": 0},
    }

    prev_raw: Optional[tuple[int, int, int]] = None

    with transaction.atomic():
        for move in moves:
            raw_after = (
                int(move.wdl_win or 0),
                int(move.wdl_draw or 0),
                int(move.wdl_loss or 0),
            )
            white_to_move = (move.ply % 2 == 1)

            adj, wdl_mu_val, delta_mu_val, delta_d_val, base_sev, draw_char = (
                _classify_one_move(
                    raw_after,
                    prev_raw,
                    white_elo,
                    black_elo,
                    white_to_move,
                    draw_rate_reference,
                )
            )

            move.wdl_win_adj = adj[0]
            move.wdl_draw_adj = adj[1]
            move.wdl_loss_adj = adj[2]
            move.wdl_mu = wdl_mu_val
            move.delta_mu = delta_mu_val
            move.delta_d = delta_d_val
            move.base_severity = base_sev
            move.draw_character = draw_char
            move.save(update_fields=_MOVE_UPDATE_FIELDS)

            # Accumulate per-side WDL probabilities and counters.
            # Use /1000 to match the worker's _accumulate_move_stats exactly:
            #   wdl_lists[i].append(wdl_white_adj[i] / 1000)
            if white_to_move:
                white_wins.append(adj[0] / 1000)
                white_draws.append(adj[1] / 1000)
                white_losses.append(adj[2] / 1000)
                side = "white"
            else:
                black_wins.append(adj[0] / 1000)
                black_draws.append(adj[1] / 1000)
                black_losses.append(adj[2] / 1000)
                side = "black"

            _update_counter(cls_counts, side, base_sev)
            prev_raw = raw_after

        # Recompute per-side probs (avg of per-ply permille fractions)
        game_analysis.white_win_prob = _avg(white_wins)
        game_analysis.white_draw_prob = _avg(white_draws)
        game_analysis.white_loss_prob = _avg(white_losses)
        game_analysis.black_win_prob = _avg(black_wins)
        game_analysis.black_draw_prob = _avg(black_draws)
        game_analysis.black_loss_prob = _avg(black_losses)
        game_analysis.white_blunders = cls_counts["white"]["blunders"]
        game_analysis.white_mistakes = cls_counts["white"]["mistakes"]
        game_analysis.white_inaccuracies = cls_counts["white"]["inaccuracies"]
        game_analysis.black_blunders = cls_counts["black"]["blunders"]
        game_analysis.black_mistakes = cls_counts["black"]["mistakes"]
        game_analysis.black_inaccuracies = cls_counts["black"]["inaccuracies"]
        game_analysis.save(update_fields=_GAME_UPDATE_FIELDS)

    log.info(
        "recompute_lc0_calibration: game_analysis %d — %d moves recomputed",
        game_analysis.pk,
        len(moves),
    )


def _update_counter(
    cls_counts: dict[str, dict[str, int]],
    side: str,
    base_severity: str,
) -> None:
    """Increment the per-side classification counter if severity warrants it.

    Args:
        cls_counts: Nested {"white"|"black": {label: count}} dict (mutated).
        side: "white" or "black".
        base_severity: Severity label from classify_draw_aware.
    """
    bucket_map = {
        "Blunder": "blunders",
        "Mistake": "mistakes",
        "Inaccuracy": "inaccuracies",
    }
    bucket = bucket_map.get(base_severity)
    if bucket and bucket in cls_counts[side]:
        cls_counts[side][bucket] += 1


class Command(BaseCommand):
    """Recompute Lc0 WDL calibration derived fields from stored raw data (#159/E1)."""

    help = (
        "Recompute Lc0MoveAnalysis derived fields (wdl_*_adj, wdl_mu, delta_mu, "
        "delta_d, base_severity, draw_character) from stored raw WDL triples and "
        "per-game calibration metadata.  No engine is launched.  "
        "Use --all to process every Lc0GameAnalysis, or --game <id> for one."
    )

    def add_arguments(self, parser):
        """Register --all and --game CLI flags.

        Args:
            parser: Django's ArgumentParser instance.
        """
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--all",
            action="store_true",
            dest="all_games",
            help="Recompute every Lc0GameAnalysis in the database.",
        )
        group.add_argument(
            "--game",
            type=int,
            dest="game_id",
            metavar="ID",
            help="Recompute a single Lc0GameAnalysis by primary key.",
        )

    def handle(self, *args, **options):
        """Entry point: dispatch to --all or --game recompute path.

        Args:
            args: Positional arguments (unused).
            options: Parsed CLI options (all_games, game_id).

        Side effects:
            Writes updated Lc0MoveAnalysis and Lc0GameAnalysis rows.

        Raises:
            CommandError: if --game ID does not match any Lc0GameAnalysis.
        """
        if options["all_games"]:
            self._handle_all()
        else:
            self._handle_one(options["game_id"])

    def _handle_all(self) -> None:
        """Recompute every Lc0GameAnalysis row.

        Returns:
            None

        Side effects:
            Processes all Lc0GameAnalysis rows; writes a summary to stdout.
        """
        queryset = Lc0GameAnalysis.objects.all()
        total = queryset.count()
        self.stdout.write(f"Recomputing {total} Lc0GameAnalysis rows …")
        skipped = 0
        processed = 0
        for game_analysis in queryset.iterator():
            if not game_analysis.draw_rate_reference:
                skipped += 1
                continue
            _recompute_game(game_analysis)
            processed += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Done — {processed} processed, {skipped} skipped "
                f"(no draw_rate_reference)."
            )
        )

    def _handle_one(self, game_id: int) -> None:
        """Recompute a single Lc0GameAnalysis by primary key.

        Args:
            game_id: Primary key of the Lc0GameAnalysis to recompute.

        Returns:
            None

        Raises:
            CommandError: if no Lc0GameAnalysis with the given PK exists.
        """
        try:
            game_analysis = Lc0GameAnalysis.objects.get(pk=game_id)
        except Lc0GameAnalysis.DoesNotExist:
            raise CommandError(f"No Lc0GameAnalysis with id={game_id} found.")
        _recompute_game(game_analysis)
        self.stdout.write(
            self.style.SUCCESS(f"Recomputed Lc0GameAnalysis id={game_id}.")
        )
