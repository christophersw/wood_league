"""
Title: dashboard_helpers.py — Pure helpers for the worker dashboard
Description:
    Pure-function helpers consumed by both the legacy queues_summary view
    and the consolidated /admin/dashboard/ partials. Includes percentile
    calculation, per-engine throughput rollups, failure-row construction,
    worker-liveness classification, rate/ETA calculation, recent-game
    grouping, and game-link resolution.

Changelog:
    2026-05-14 (#106): Initial extraction from views.py (#86) + new
        dashboard-specific helpers.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone

from analysis.models import AnalysisJob


__all__ = [
    "_percentile",
    "_engine_throughput_row",
    "_throughput_for_window",
    "_failure_timestamp",
    "_worker_log_url_for",
    "_build_failure_row",
]


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    """Compute a linear-interpolated percentile from a sorted value list.

    Mirrors Postgres ``percentile_cont`` semantics for parity with the
    production database while keeping the helper usable on SQLite test
    backends.

    Args:
        sorted_values: Pre-sorted (ascending) list of finite floats.
        fraction: Percentile fraction in the closed interval [0.0, 1.0].

    Returns:
        The interpolated percentile value, or ``None`` if the input list
        is empty.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = fraction * (len(sorted_values) - 1)
    lower_index = int(pos)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = pos - lower_index
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    return lower_value + (upper_value - lower_value) * weight


def _engine_throughput_row(engine: str, hours: int) -> dict[str, Any]:
    """Compute throughput metrics for one engine over the last ``hours``.

    Args:
        engine: Engine name (e.g. ``"stockfish"`` or ``"lc0"``).
        hours: Window length, in hours, ending at the current time.

    Returns:
        Dict with keys ``engine``, ``completed``, ``games_per_hour``,
        ``avg_seconds``, ``p50_seconds``, ``p95_seconds`` and
        ``failure_rate``. Numeric values are rounded to 2 decimals or
        ``None`` when no completed jobs exist.
    """
    cutoff = timezone.now() - timedelta(hours=hours)
    base_qs = AnalysisJob.objects.filter(
        engine=engine,
        completed_at__gte=cutoff,
        status__in=(AnalysisJob.STATUS_COMPLETED, AnalysisJob.STATUS_FAILED),
    )
    completed_durations = list(
        AnalysisJob.objects.filter(
            engine=engine,
            completed_at__gte=cutoff,
            status=AnalysisJob.STATUS_COMPLETED,
            duration_seconds__isnull=False,
        ).values_list("duration_seconds", flat=True)
    )
    completed_count = len(completed_durations)
    finished_count = base_qs.count()
    failed_count = finished_count - completed_count

    sorted_durations = sorted(float(d) for d in completed_durations)
    avg_value = (
        sum(sorted_durations) / completed_count if completed_count else None
    )
    p50_value = _percentile(sorted_durations, 0.5)
    p95_value = _percentile(sorted_durations, 0.95)
    failure_rate = (failed_count / finished_count) if finished_count else 0.0

    return {
        "engine": engine,
        "completed": completed_count,
        "games_per_hour": round(completed_count / hours, 2) if hours else 0.0,
        "avg_seconds": round(avg_value, 2) if avg_value is not None else None,
        "p50_seconds": round(p50_value, 2) if p50_value is not None else None,
        "p95_seconds": round(p95_value, 2) if p95_value is not None else None,
        "failure_rate": round(failure_rate, 4),
    }


def _throughput_for_window(hours: int = 24) -> list[dict[str, Any]]:
    """Return per-engine throughput rows for the last ``hours``.

    Args:
        hours: Length of the rolling time window. Defaults to 24.

    Returns:
        A list with one dict per known engine (stockfish, lc0). Each dict
        carries the keys produced by :func:`_engine_throughput_row`.
    """
    return [_engine_throughput_row(engine, hours) for engine in ("stockfish", "lc0")]


def _failure_timestamp(job: AnalysisJob) -> Any:
    """Return the most relevant timestamp for a failed analysis job.

    Prefers ``completed_at``, then ``last_error_at``, then ``created_at``.

    Args:
        job: The :class:`AnalysisJob` instance.

    Returns:
        The first non-null timestamp from the preference list, or
        ``created_at`` as a fallback.
    """
    return job.completed_at or job.last_error_at or job.created_at


def _worker_log_url_for(job: AnalysisJob) -> str | None:
    """Return the admin change URL for the WorkerLogUpload matching a job.

    A log is considered a match when its owning ``WorkerAPIKey.prefix``
    equals ``job.claimed_by_key_prefix`` and its ``uploaded_at`` lies
    within one hour of the failure timestamp.

    Args:
        job: The failed :class:`AnalysisJob` we want a log link for.

    Returns:
        An admin URL string when a matching upload row is found, else
        ``None``.
    """
    prefix = job.claimed_by_key_prefix
    failure_time = _failure_timestamp(job)
    if not prefix or failure_time is None:
        return None
    from api.models import WorkerLogUpload  # local import: avoid app-load cycle

    window_start = failure_time - timedelta(hours=1)
    window_end = failure_time + timedelta(hours=1)
    upload = (
        WorkerLogUpload.objects
        .filter(worker__prefix=prefix)
        .filter(uploaded_at__gte=window_start, uploaded_at__lte=window_end)
        .order_by("-uploaded_at")
        .first()
    )
    if upload is None:
        return None
    return reverse("admin:api_workerlogupload_change", args=[upload.pk])


def _build_failure_row(job: AnalysisJob) -> dict[str, Any]:
    """Convert one failed :class:`AnalysisJob` into a template row dict.

    Args:
        job: The job to summarise.

    Returns:
        Dict with keys ``id``, ``game_id``, ``game_url``, ``engine``,
        ``worker_id``, ``completed_at``, ``retry_count``, ``error_snippet``
        and ``worker_log_url`` (any of which may be empty/None).
    """
    raw_error = job.error_message or job.last_error or ""
    snippet = raw_error[:200]
    game = job.game
    game_url: str | None = None
    if game and game.slug:
        game_url = reverse("games:analysis", args=[game.slug])
    return {
        "id": job.id,
        "game_id": job.game_id,
        "game_url": game_url,
        "engine": job.engine,
        "worker_id": job.worker_id,
        "completed_at": _failure_timestamp(job),
        "retry_count": job.retry_count,
        "error_snippet": snippet,
        "worker_log_url": _worker_log_url_for(job),
    }
