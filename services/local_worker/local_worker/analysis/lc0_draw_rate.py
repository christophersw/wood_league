"""
Title: lc0_draw_rate.py — per-network reference draw-rate measurement
Description:
    Measures a network's reference draw rate by sampling lc0's WDL. Samples
    the start position repeatedly when multi-threaded search is
    nondeterministic; otherwise sweeps a curated opening-FEN set. Stops when
    the sample standard error of the mean draw fraction (Bessel n-1) drops
    below sem_target or a sample cap is hit. Persisted per network via
    lc0_tuning_sync so the rescale always has a measured reference (issue #159).
Changelog:
    2026-05-19: Initial creation (issue #159).
    2026-05-19: Fix combined sample accumulation — nondeterministic-phase
                samples are now carried into the curated-FEN phase so
                DrawRateResult reflects the full sample set (issue #159 FIX 2).
    2026-05-19: Fix pstdev → stdev (Bessel n-1) for unbiased SEM at both
                SEM-check and final stderr computation (issue #159 B1).
"""
from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any

import chess
import chess.engine

from .draw_rate_fens import CURATED_OPENING_FENS

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrawRateResult:
    """Measured reference draw rate for a network.

    Attributes:
        network: resolved network name.
        draw_rate_reference: mean draw fraction in (0, 1), clamped to
            lc0's option range [0.001, 0.999].
        n_samples: number of positions sampled.
        stderr: standard error of the mean draw fraction.
    """

    network: str
    draw_rate_reference: float
    n_samples: int
    stderr: float


def _draw_fraction(engine: Any, board: chess.Board, nodes: int) -> float:
    """Return lc0's draw permille / 1000 for one position (White frame).

    Args:
        engine: Running lc0 SimpleEngine (or compatible mock).
        board: Position to evaluate.
        nodes: Node budget for the search.

    Returns:
        Draw probability in [0, 1].
    """
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    wdl = info["score"].pov(chess.WHITE).wdl()
    total = wdl.wins + wdl.draws + wdl.losses
    return (wdl.draws / total) if total else 0.0


def _sem_below_target(samples: list[float], sem_target: float) -> bool:
    """Return True when the sample standard error of the mean is below sem_target.

    Uses the sample standard deviation (Bessel n-1 correction) so the SEM
    estimate is unbiased.  Requires at least 3 samples; returns False when
    fewer samples exist (n>=3 also satisfies stdev's n>=2 requirement).

    Args:
        samples: List of draw-fraction observations.
        sem_target: Target SEM threshold.

    Returns:
        True if SEM < sem_target, False otherwise.
    """
    if len(samples) < 3:
        return False
    # stdev (Bessel n-1) gives the sample standard deviation; >=3 guard above
    # satisfies stdev's n>=2 requirement.
    sd = statistics.stdev(samples)
    sem = sd / math.sqrt(len(samples))
    return sem < sem_target


def _collect_deterministic_samples(
    engine: Any,
    nodes: int,
    prior_samples: list[float],
    max_samples: int,
    sem_target: float,
) -> list[float]:
    """Sweep CURATED_OPENING_FENS once the search is known to be deterministic.

    Appends curated-FEN samples to the already-accumulated prior_samples until
    sem_target is met, max_samples is reached, or the full curated FEN set is
    exhausted.  The combined list (prior + new) is returned so callers always
    compute statistics over the full sample set.

    Args:
        engine: Running lc0 engine.
        nodes: Node budget per sample.
        prior_samples: All draw-fraction samples accumulated before this phase
            (may include nondeterministic startpos samples).
        max_samples: Hard cap on total samples (across all phases).
        sem_target: Target SEM threshold.

    Returns:
        Combined list of draw-fraction samples (prior_samples + curated FENs).
    """
    samples = list(prior_samples)
    for fen in CURATED_OPENING_FENS:
        if len(samples) >= max_samples:
            break
        samples.append(_draw_fraction(engine, chess.Board(fen), nodes))
        if _sem_below_target(samples, sem_target):
            break
    return samples


def _collect_nondeterministic_samples(
    engine: Any,
    nodes: int,
    first_sample: float,
    max_samples: int,
    sem_target: float,
) -> list[float]:
    """Sample startpos repeatedly until determinism is detected or cap reached.

    Switches to the curated FEN sweep as soon as two consecutive startpos
    results are identical (deterministic search detected).  All samples from
    the nondeterministic phase are carried into the deterministic phase so
    the final list covers the combined sample set.

    Args:
        engine: Running lc0 engine.
        nodes: Node budget per sample.
        first_sample: First startpos sample already collected.
        max_samples: Hard cap on total samples (across all phases).
        sem_target: Target SEM threshold.

    Returns:
        Full list of draw-fraction samples (nondeterministic + curated FENs).
    """
    samples = [first_sample]
    prev = first_sample
    while len(samples) < max_samples:
        nxt = _draw_fraction(engine, chess.Board(), nodes)
        samples.append(nxt)
        if math.isclose(nxt, prev, abs_tol=1e-9):
            # Deterministic: switch to curated FENs, carrying ALL prior samples
            return _collect_deterministic_samples(
                engine, nodes, samples, max_samples, sem_target
            )
        prev = nxt
        if _sem_below_target(samples, sem_target):
            break
    return samples


def measure_draw_rate(
    engine: Any,
    *,
    network: str,
    sem_target: float = 0.005,
    max_samples: int = 64,
    nodes: int = 1,
) -> DrawRateResult:
    """Measure a network's reference draw rate.

    Strategy: sample startpos repeatedly; once two consecutive startpos
    samples are identical (deterministic search detected) switch to sweeping
    CURATED_OPENING_FENS. Stop when SEM < sem_target (>=3 samples) or
    max_samples reached. Clamp to lc0's [0.001, 0.999] option range.

    Args:
        engine: Running lc0 SimpleEngine (or compatible mock).
        network: Resolved network name (persistence key).
        sem_target: Target standard error of the mean. Pass 0.0 to exhaust
            max_samples entirely.
        max_samples: Hard cap on positions sampled.
        nodes: Node budget per sample.

    Returns:
        DrawRateResult with the measured draw rate and diagnostics.
    """
    first = _draw_fraction(engine, chess.Board(), nodes)
    samples = _collect_nondeterministic_samples(
        engine, nodes, first, max_samples, sem_target
    )
    mean = sum(samples) / len(samples)
    # stdev (Bessel n-1) gives the sample standard deviation for SEM.
    # len>1 guard satisfies stdev's n>=2 requirement.
    sd = statistics.stdev(samples) if len(samples) > 1 else 0.0
    sem = sd / math.sqrt(len(samples)) if samples else 0.0
    draw_rate_reference = min(0.999, max(0.001, mean))
    log.info(
        "lc0: measured draw_rate_reference=%.4f n=%d sem=%.4f net=%s",
        draw_rate_reference,
        len(samples),
        sem,
        network,
    )
    return DrawRateResult(network, draw_rate_reference, len(samples), sem)
