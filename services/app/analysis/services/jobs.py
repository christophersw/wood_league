"""
Title: jobs.py — Analysis job service layer
Description:
    Shared business logic for analysis job management including claiming,
    completing, and failing jobs. Used by both management commands and API views
    to maintain consistency across the analysis workflow.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-08: Added submit_job() for RunPod dispatcher integration
    2026-05-10: Removed dispatch_mode from claim_jobs, recover_stale_jobs, and submit_job
    2026-05-15: fail_job() now treats "PGN has no moves" errors as
        permanent failures (no retry) — issue #112.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analysis.calibration_hash import (
    current_lc0_sampler_settings,
    current_lc0_settings_hash,
)
from analysis.models import (
    AnalysisJob,
    GameAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
    MoveAnalysis,
    NetworkCalibration,
)


# ── Constants ────────────────────────────────────────────────────────────
class JobCheckoutDenied(Exception):
    """Raised when a requested job checkout cannot be honored."""


class NeedsCalibration(Exception):
    """Raised when an lc0 checkout arrives for an uncalibrated network.

    Carries the metadata the worker needs to drive the calibration sampler:
    the resolved ``network_name``, the current ``settings_hash`` to echo
    back on submission, the canonical sampler settings, and the sampler
    version tag. The view layer translates this exception into a 409
    response with ``error="NEEDS_CALIBRATION"``.
    """

    def __init__(
        self,
        *,
        network_name: str,
        settings_hash: str,
        sampler_settings: dict,
        sampler_version: str,
    ) -> None:
        """Capture the calibration request payload.

        Args:
            network_name: Resolved lc0 network identifier.
            settings_hash: Current canonical sampler-settings hash.
            sampler_settings: Canonical settings dict the worker must use.
            sampler_version: Echoes settings.WL_LC0_DRAW_RATE_SAMPLER_VERSION.
        """
        super().__init__(f"NEEDS_CALIBRATION for {network_name}")
        self.network_name = network_name
        self.settings_hash = settings_hash
        self.sampler_settings = sampler_settings
        self.sampler_version = sampler_version


# Error substrings that signal the job is structurally unanalysable. Retrying
# these is wasted work — fail them permanently on first report (issue #112).
_PERMANENT_FAILURE_MARKERS = (
    "PGN has no moves",
)


def _is_permanent_failure(error: str) -> bool:
    """Return True when the worker error is non-retryable by design."""
    return any(marker in error for marker in _PERMANENT_FAILURE_MARKERS)


def _analysis_already_completed(*, engine: str, game_id: str) -> bool:
    """Return True when the requested game already has completed analysis for the engine."""
    if engine == 'stockfish':
        return GameAnalysis.objects.filter(game_id=game_id).exists()
    return Lc0GameAnalysis.objects.filter(game_id=game_id).exists()


def _stale_timeout() -> timedelta:
    """Return the timeout duration for considering a job stale."""
    return timedelta(minutes=settings.STALE_JOB_TIMEOUT_MINUTES)


def _max_retries() -> int:
    """Return the maximum number of retries before a job is marked failed."""
    return settings.MAX_JOB_RETRIES


# ── Stale recovery ───────────────────────────────────────────────────────


def recover_stale_jobs(engine: str) -> int:
    """Reset jobs stuck in 'running' for longer than STALE_JOB_TIMEOUT_MINUTES.

    Called automatically before every checkout. Returns the number of jobs recovered.
    """
    cutoff = timezone.now() - _stale_timeout()
    return AnalysisJob.objects.filter(
        engine=engine,
        status=AnalysisJob.STATUS_RUNNING,
        started_at__lt=cutoff,
    ).update(
        status=AnalysisJob.STATUS_PENDING,
        worker_id=None,
        started_at=None,
        claimed_at=None,
        claimed_by_key_prefix=None,
    )


# ── Claim jobs ───────────────────────────────────────────────────────────


def _resolve_lc0_calibration(network_name: str) -> float:
    """Resolve the current draw_rate_reference for ``network_name``.

    Args:
        network_name: Resolved lc0 network identifier supplied by the worker.

    Returns:
        The ``draw_rate_reference`` stored on the matching NetworkCalibration
        row.

    Raises:
        NeedsCalibration: When no calibration row exists for the current
            ``(network_name, settings_hash)`` pair. The exception carries the
            sampler settings the worker must use.
    """
    settings_hash = current_lc0_settings_hash()
    row = NetworkCalibration.objects.filter(
        network_name=network_name, settings_hash=settings_hash,
    ).only("draw_rate_reference").first()
    if row is None:
        sampler = current_lc0_sampler_settings()
        raise NeedsCalibration(
            network_name=network_name,
            settings_hash=settings_hash,
            sampler_settings=sampler,
            sampler_version=sampler["sampler_version"],
        )
    return row.draw_rate_reference


def _select_single_game_job(*, engine: str, game_id: str) -> list[AnalysisJob]:
    """Return the one pending AnalysisJob for ``game_id`` under SELECT FOR UPDATE.

    Args:
        engine: 'stockfish' or 'lc0'.
        game_id: The specific game whose pending job to claim.

    Returns:
        A single-element list with the locked pending job.

    Raises:
        JobCheckoutDenied: When the game is already completed, already running,
            or has no pending job for this engine.
    """
    jobs_for_game = (
        AnalysisJob.objects
        .select_for_update(skip_locked=True)
        .filter(engine=engine, game_id=game_id)
    )
    if (
        _analysis_already_completed(engine=engine, game_id=game_id)
        or jobs_for_game.filter(status=AnalysisJob.STATUS_COMPLETED).exists()
    ):
        raise JobCheckoutDenied('Analysis already completed for requested game')
    if jobs_for_game.filter(status=AnalysisJob.STATUS_RUNNING).exists():
        raise JobCheckoutDenied('Requested game is already claimed')
    jobs = list(
        jobs_for_game
        .filter(status=AnalysisJob.STATUS_PENDING)
        .order_by('-priority', '-game__played_at')[:1]
    )
    if not jobs:
        raise JobCheckoutDenied('No pending job exists for requested game')
    return jobs


def claim_jobs(
    *,
    engine: str,
    batch_size: int,
    worker_id: str,
    key_prefix: str | None = None,
    game_id: str | None = None,
    network_name: str = "",
) -> list[AnalysisJob]:
    """Atomically claim up to batch_size pending jobs using SELECT FOR UPDATE SKIP LOCKED.

    Runs stale recovery before each checkout. For lc0 checkouts that supply a
    ``network_name``, pre-flights the network's calibration row and raises
    ``NeedsCalibration`` when one is absent (issue #161 Phase B). Returns the
    claimed AnalysisJob instances with their related Game.

    Args:
        engine: 'stockfish' or 'lc0'.
        batch_size: Maximum number of jobs to claim.
        worker_id: Identifier for the claiming worker (stored for tracing).
        key_prefix: API key prefix stored for audit (None for non-API callers).
        game_id: Claim only this specific game's job (optional).
        network_name: For lc0 only: the worker's resolved network name. When
            empty, the calibration pre-flight is skipped (legacy/test paths).
    """
    draw_rate_reference: float | None = None
    if engine == "lc0" and network_name:
        draw_rate_reference = _resolve_lc0_calibration(network_name)
    with transaction.atomic():
        recover_stale_jobs(engine)
        if game_id:
            jobs = _select_single_game_job(engine=engine, game_id=game_id)
        else:
            jobs = list(
                AnalysisJob.objects
                .select_for_update(skip_locked=True)
                .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
                .order_by('-priority', '-game__played_at')
                [:batch_size]
            )
        if not jobs:
            return []
        now = timezone.now()
        job_ids = [j.id for j in jobs]
        AnalysisJob.objects.filter(id__in=job_ids).update(
            status=AnalysisJob.STATUS_RUNNING,
            started_at=now,
            claimed_at=now,
            worker_id=worker_id,
            claimed_by_key_prefix=key_prefix,
        )
        claimed = list(
            AnalysisJob.objects
            .filter(id__in=job_ids)
            .select_related('game')
        )
        if draw_rate_reference is not None:
            # Transient annotation read by JobSerializer; not persisted.
            for job in claimed:
                job.draw_rate_reference = draw_rate_reference
        return claimed


# ── Complete: Stockfish ──────────────────────────────────────────────────


def complete_stockfish_job(
    *,
    job_id: int,
    worker_id: str,
    key_prefix: str | None,
    payload: dict,
) -> None:
    """Write Stockfish results and mark the job completed.

    Raises AnalysisJob.DoesNotExist if the job is not found,
    not in 'running' state, or the worker_id / key_prefix do not match.
    """
    # #161 Phase G: payload is *raw observables only*; everything derived runs
    # here via ``derivation.stockfish.derive_sf_game``.
    from analysis.derivation.stockfish import derive_sf_game

    with transaction.atomic():
        # Ownership check: worker_id AND key_prefix must match the claim
        filters = dict(
            id=job_id,
            status=AnalysisJob.STATUS_RUNNING,
            worker_id=worker_id,
        )
        if key_prefix is not None:
            filters['claimed_by_key_prefix'] = key_prefix
        job = AnalysisJob.objects.select_for_update().get(**filters)

        derived = derive_sf_game(payload, job.game)
        derived_moves = derived.pop("moves")

        ga, _ = GameAnalysis.objects.update_or_create(
            game=job.game,
            defaults=dict(
                white_accuracy=derived["white_accuracy"],
                black_accuracy=derived["black_accuracy"],
                white_acpl=derived["white_acpl"],
                black_acpl=derived["black_acpl"],
                white_blunders=derived["white_blunders"],
                white_mistakes=derived["white_mistakes"],
                white_inaccuracies=derived["white_inaccuracies"],
                black_blunders=derived["black_blunders"],
                black_mistakes=derived["black_mistakes"],
                black_inaccuracies=derived["black_inaccuracies"],
                engine_depth=derived["engine_depth"],
                summary_cp=derived["summary_cp"],
                analyzed_at=timezone.now(),
            ),
        )

        MoveAnalysis.objects.filter(analysis=ga).delete()
        MoveAnalysis.objects.bulk_create([
            MoveAnalysis(
                analysis=ga,
                ply=m["ply"],
                san=m["san"],
                fen=m["fen"],
                cp_eval=m["cp_eval"],
                mate_in=m["mate_in"],
                cpl=m["cpl"],
                move_win_delta=m["move_win_delta"],
                classification=m["classification"],
                best_move=m["best_move"],
                arrow_uci_1=m["arrow_uci_1"] or "",
                arrow_uci_2=m["arrow_uci_2"],
                arrow_uci_3=m["arrow_uci_3"],
                pv_san_1=m["pv_san_1"],
                pv_san_2=m["pv_san_2"],
                pv_san_3=m["pv_san_3"],
            )
            for m in derived_moves
        ])

        job.status = AnalysisJob.STATUS_COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])


# ── Complete: Lc0 ───────────────────────────────────────────────────────


def complete_lc0_job(
    *,
    job_id: int,
    worker_id: str,
    key_prefix: str | None,
    payload: dict,
) -> None:
    """Write Lc0 results and mark the job completed.

    Same ownership semantics as complete_stockfish_job.
    """
    # #161 Phase G: payload is *raw observables only*; everything derived runs
    # here via ``derivation.lc0.derive_lc0_game``.
    from analysis.derivation.lc0 import derive_lc0_game

    with transaction.atomic():
        filters = dict(
            id=job_id,
            status=AnalysisJob.STATUS_RUNNING,
            worker_id=worker_id,
        )
        if key_prefix is not None:
            filters['claimed_by_key_prefix'] = key_prefix
        job = AnalysisJob.objects.select_for_update().get(**filters)

        derived = derive_lc0_game(payload, job.game)
        derived_moves = derived.pop("moves")

        lga, _ = Lc0GameAnalysis.objects.update_or_create(
            game=job.game,
            defaults=dict(
                white_win_prob=derived["white_win_prob"],
                white_draw_prob=derived["white_draw_prob"],
                white_loss_prob=derived["white_loss_prob"],
                black_win_prob=derived["black_win_prob"],
                black_draw_prob=derived["black_draw_prob"],
                black_loss_prob=derived["black_loss_prob"],
                white_blunders=derived["white_blunders"],
                white_mistakes=derived["white_mistakes"],
                white_inaccuracies=derived["white_inaccuracies"],
                black_blunders=derived["black_blunders"],
                black_mistakes=derived["black_mistakes"],
                black_inaccuracies=derived["black_inaccuracies"],
                engine_nodes=derived["engine_nodes"],
                network_name=derived["network_name"],
                draw_rate_reference=derived["draw_rate_reference"],
                wdl_calibration_elo=derived["wdl_calibration_elo"],
                contempt=derived["contempt"],
                white_accuracy=derived["white_accuracy"],
                black_accuracy=derived["black_accuracy"],
                analyzed_at=timezone.now(),
            ),
        )

        Lc0MoveAnalysis.objects.filter(analysis=lga).delete()
        Lc0MoveAnalysis.objects.bulk_create([
            Lc0MoveAnalysis(
                analysis=lga,
                ply=m["ply"],
                san=m["san"],
                fen=m["fen"],
                # Raw played-move triple (mover frame).
                wdl_win=m["wdl_win"],
                wdl_draw=m["wdl_draw"],
                wdl_loss=m["wdl_loss"],
                # Raw per-candidate triples.
                wdl_win_1=m["wdl_win_1"],
                wdl_draw_1=m["wdl_draw_1"],
                wdl_loss_1=m["wdl_loss_1"],
                wdl_win_2=m["wdl_win_2"],
                wdl_draw_2=m["wdl_draw_2"],
                wdl_loss_2=m["wdl_loss_2"],
                wdl_win_3=m["wdl_win_3"],
                wdl_draw_3=m["wdl_draw_3"],
                wdl_loss_3=m["wdl_loss_3"],
                # Derived (post-rescale, post-classify).
                wdl_win_adj=m["wdl_win_adj"],
                wdl_draw_adj=m["wdl_draw_adj"],
                wdl_loss_adj=m["wdl_loss_adj"],
                wdl_mu=m["wdl_mu"],
                delta_mu=m["delta_mu"],
                delta_d=m["delta_d"],
                base_severity=m["base_severity"],
                draw_character=m["draw_character"],
                best_move=m["arrow_uci_1"] or "",
                arrow_uci_1=m["arrow_uci_1"] or "",
                arrow_uci_2=m["arrow_uci_2"],
                arrow_uci_3=m["arrow_uci_3"],
                pv_san_1=m["pv_san_1"],
                pv_san_2=m["pv_san_2"],
                pv_san_3=m["pv_san_3"],
            )
            for m in derived_moves
        ])

        job.status = AnalysisJob.STATUS_COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])


# ── Fail a job ───────────────────────────────────────────────────────────


def fail_job(
    *,
    job_id: int,
    worker_id: str,
    key_prefix: str | None,
    error: str,
) -> str:
    """Increment retry_count. Requeue if under MAX_JOB_RETRIES, else mark failed.

    Returns 'requeued' or 'failed'.
    """
    with transaction.atomic():
        filters = dict(
            id=job_id,
            status=AnalysisJob.STATUS_RUNNING,
            worker_id=worker_id,
        )
        if key_prefix is not None:
            filters['claimed_by_key_prefix'] = key_prefix
        job = AnalysisJob.objects.select_for_update().get(**filters)

        job.retry_count += 1
        job.error_message = error[:2000]

        if _is_permanent_failure(error) or job.retry_count >= _max_retries():
            job.status = AnalysisJob.STATUS_FAILED
            outcome = 'failed'
        else:
            job.status = AnalysisJob.STATUS_PENDING
            job.worker_id = None
            job.claimed_by_key_prefix = None
            job.claimed_at = None
            outcome = 'requeued'

        job.save()
        return outcome


# ── Submit a RunPod job ──────────────────────────────────────────────────


def submit_job(*, job_id: int, runpod_job_id: str) -> None:
    """Record a RunPod submission: set status=submitted and store runpod_job_id.

    Atomically transitions the job from pending → submitted and records the
    external RunPod job identifier for tracking purposes.

    Parameters:
        job_id: Primary key of the AnalysisJob to submit.
        runpod_job_id: The RunPod job identifier returned by the dispatch API.

    Returns:
        None

    Raises:
        AnalysisJob.DoesNotExist: If the job is not found or not in pending state.
    """
    with transaction.atomic():
        job = AnalysisJob.objects.select_for_update().get(
            id=job_id,
            status=AnalysisJob.STATUS_PENDING,
        )
        job.status = AnalysisJob.STATUS_SUBMITTED
        job.runpod_job_id = runpod_job_id
        job.submitted_at = timezone.now()
        job.save(update_fields=['status', 'runpod_job_id', 'submitted_at'])
