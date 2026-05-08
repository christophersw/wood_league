"""Service layer for analysis job management.

This module provides the shared business logic for claiming, completing, and
failing analysis jobs. Both the management commands and API views use these
functions to maintain consistency.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from analysis.models import (
    AnalysisJob,
    GameAnalysis,
    MoveAnalysis,
    Lc0GameAnalysis,
    Lc0MoveAnalysis,
)


# ── Constants ────────────────────────────────────────────────────────────
class JobCheckoutDenied(Exception):
    """Raised when a requested job checkout cannot be honored."""


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


def claim_jobs(
    *,
    engine: str,
    batch_size: int,
    worker_id: str,
    key_prefix: str | None = None,
    game_id: str | None = None,
) -> list[AnalysisJob]:
    """Atomically claim up to batch_size pending jobs using SELECT FOR UPDATE SKIP LOCKED.

    Runs stale recovery first. Returns the claimed AnalysisJob instances with their
    related Game.
    """
    with transaction.atomic():
        recover_stale_jobs(engine)
        if game_id:
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
                .order_by('-priority', 'created_at')[:1]
            )
            if not jobs:
                raise JobCheckoutDenied('No pending job exists for requested game')
        else:
            jobs = list(
                AnalysisJob.objects
                .select_for_update(skip_locked=True)
                .filter(engine=engine, status=AnalysisJob.STATUS_PENDING)
                .order_by('-priority', 'created_at')
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
        return list(
            AnalysisJob.objects
            .filter(id__in=job_ids)
            .select_related('game')
        )


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

        # Upsert game_analysis
        GameAnalysis.objects.update_or_create(
            game=job.game,
            defaults=dict(
                white_accuracy=payload['white_accuracy'],
                black_accuracy=payload['black_accuracy'],
                white_acpl=payload['white_acpl'],
                black_acpl=payload['black_acpl'],
                white_blunders=payload['white_blunders'],
                white_mistakes=payload['white_mistakes'],
                white_inaccuracies=payload['white_inaccuracies'],
                black_blunders=payload['black_blunders'],
                black_mistakes=payload['black_mistakes'],
                black_inaccuracies=payload['black_inaccuracies'],
                engine_depth=payload['engine_depth'],
                analyzed_at=timezone.now(),
            ),
        )

        # Replace move_analysis rows for this game
        MoveAnalysis.objects.filter(game=job.game).delete()
        MoveAnalysis.objects.bulk_create([
            MoveAnalysis(
                game=job.game,
                ply=m['ply'],
                san=m['san'],
                fen=m['fen'],
                cp_eval=m['cp_eval'],
                cpl=m['cpl'],
                best_move=m['best_move'],
                classification=m['classification'],
            )
            for m in payload['moves']
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
    with transaction.atomic():
        filters = dict(
            id=job_id,
            status=AnalysisJob.STATUS_RUNNING,
            worker_id=worker_id,
        )
        if key_prefix is not None:
            filters['claimed_by_key_prefix'] = key_prefix
        job = AnalysisJob.objects.select_for_update().get(**filters)

        Lc0GameAnalysis.objects.update_or_create(
            game=job.game,
            defaults=dict(
                white_win_prob=payload['white_win_prob'],
                white_draw_prob=payload['white_draw_prob'],
                white_loss_prob=payload['white_loss_prob'],
                black_win_prob=payload['black_win_prob'],
                black_draw_prob=payload['black_draw_prob'],
                black_loss_prob=payload['black_loss_prob'],
                white_blunders=payload['white_blunders'],
                white_mistakes=payload['white_mistakes'],
                white_inaccuracies=payload['white_inaccuracies'],
                black_blunders=payload['black_blunders'],
                black_mistakes=payload['black_mistakes'],
                black_inaccuracies=payload['black_inaccuracies'],
                engine_nodes=payload['engine_nodes'],
                network_name=payload.get('network_name', ''),
                analyzed_at=timezone.now(),
            ),
        )

        Lc0MoveAnalysis.objects.filter(game=job.game).delete()
        Lc0MoveAnalysis.objects.bulk_create([
            Lc0MoveAnalysis(
                game=job.game,
                ply=m['ply'],
                san=m['san'],
                fen=m['fen'],
                wdl_win=m['wdl_win'],
                wdl_draw=m['wdl_draw'],
                wdl_loss=m['wdl_loss'],
                cp_equiv=m.get('cp_equiv'),
                best_move=m['best_move'],
                arrow_uci=m.get('arrow_uci', ''),
                move_win_delta=m['move_win_delta'],
                classification=m['classification'],
            )
            for m in payload['moves']
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

        if job.retry_count >= _max_retries():
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
