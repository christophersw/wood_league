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
    2026-05-14 (#106): Added _rate_per_min and _eta_for for queues partial.
    2026-05-14 (#106): Added _group_recent_by_game for recent partial.
    2026-05-17 (#128): Added LIVE_WINDOW_SECONDS, STALE_DROP_SECONDS,
        and _worker_live_state for worker card grid.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.urls import reverse
from django.utils import timezone

from analysis.models import AnalysisJob


__all__ = [
    "LIVENESS_HEALTHY_SECONDS",
    "LIVENESS_WARNING_SECONDS",
    "_percentile",
    "_engine_throughput_row",
    "_throughput_for_window",
    "_failure_timestamp",
    "_worker_log_url_for",
    "_build_failure_row",
    "_liveness_for",
    "_format_uptime",
    "_format_memory_mb",
    "_game_link_for",
    "_rate_per_min",
    "_eta_for",
    "_group_recent_by_game",
    "LIVE_WINDOW_SECONDS",
    "STALE_DROP_SECONDS",
    "_worker_live_state",
]


LIVENESS_HEALTHY_SECONDS = 60
LIVENESS_WARNING_SECONDS = 120

# Workers-dashboard windows (issue #128). Distinct from the banner's
# 60s/120s health buckets above — these only gate the workers card grid.
LIVE_WINDOW_SECONDS = 300       # heartbeat within this → "live" highlight
STALE_DROP_SECONDS = 1800       # heartbeat older than this → not rendered


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


def _liveness_for(delta: timedelta | None) -> str:
    """Classify a "time since last_seen" delta into a liveness bucket.

    Args:
        delta: ``now - last_seen``, or ``None`` if no heartbeat exists.

    Returns:
        ``"healthy"`` when below 60s, ``"warning"`` when in [60s, 120s),
        ``"stale"`` at or above 120s and for ``None``.
    """
    if delta is None:
        return "stale"
    seconds = delta.total_seconds()
    if seconds < LIVENESS_HEALTHY_SECONDS:
        return "healthy"
    if seconds < LIVENESS_WARNING_SECONDS:
        return "warning"
    return "stale"


def _worker_live_state(delta: timedelta | None) -> str | None:
    """Classify a worker's heartbeat recency for the workers dashboard.

    Distinct from :func:`_liveness_for` (which drives the banner's
    60s/120s health buckets). Here we only need three outcomes:
    genuinely live, reporting-but-not-live, or too stale to render.

    Args:
        delta: ``now - last_seen``, or ``None`` if no heartbeat exists.

    Returns:
        ``"live"`` when within ``LIVE_WINDOW_SECONDS``; ``"reporting"``
        when older but within ``STALE_DROP_SECONDS``; ``None`` when the
        worker is too stale to show (caller should drop it) or ``delta``
        is ``None``.
    """
    if delta is None:
        return None
    seconds = delta.total_seconds()
    if seconds < LIVE_WINDOW_SECONDS:
        return "live"
    if seconds < STALE_DROP_SECONDS:
        return "reporting"
    return None


def _format_uptime(delta: timedelta | None) -> str:
    """Format ``now - started_at`` as a compact human string.

    Args:
        delta: Worker uptime, or ``None`` if not reported.

    Returns:
        ``"—"`` for ``None``; ``"Ns"`` under a minute; ``"Nm"`` under an
        hour; ``"Xh Ym"`` under a day; ``"Xd Yh"`` otherwise.
    """
    if delta is None:
        return "—"
    total = int(delta.total_seconds())
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m"
    if total < 86400:
        hours, rem = divmod(total, 3600)
        return f"{hours}h {rem // 60}m"
    days, rem = divmod(total, 86400)
    return f"{days}d {rem // 3600}h"


def _format_memory_mb(mb: int | None) -> str:
    """Format a megabyte count as MB or GB depending on magnitude.

    Args:
        mb: Memory in megabytes, or ``None``.

    Returns:
        ``"—"`` for ``None``; ``"<N> MB"`` below 1024; ``"<N>.<d> GB"``
        above.
    """
    if mb is None:
        return "—"
    if mb < 1024:
        return f"{mb} MB"
    return f"{mb / 1024:.1f} GB"


def _game_link_for(current_game_id: str | None) -> tuple[str, str | None]:
    """Resolve a worker's ``current_game_id`` to a (label, URL) tuple.

    Workers store ``current_game_id`` as ``str(Game.pk)``. We look the
    game up to get its ``slug`` for URL construction; if it is missing
    we still return a label so the card has something to show.

    Args:
        current_game_id: The string stored on ``WorkerHeartbeat``.

    Returns:
        ``(label, url)`` — label is ``"#<id>"`` or ``"—"`` when empty;
        url is the game analysis page URL when the lookup succeeds,
        else ``None``.
    """
    if not current_game_id:
        return ("—", None)
    label = f"#{current_game_id}"
    from games.models import Game  # local import: avoid app-load cycle

    slug = (
        Game.objects.filter(pk=current_game_id)
        .values_list("slug", flat=True)
        .first()
    )
    if slug is None:
        return (label, None)
    return (label, reverse("games:analysis", kwargs={"slug": slug}))


def _rate_per_min(engine: str, window_minutes: int = 10) -> float:
    """Per-minute completion rate over the last ``window_minutes``.

    Args:
        engine: Engine name to filter on.
        window_minutes: Trailing window length. Defaults to 10.

    Returns:
        Completions in window divided by ``window_minutes``.
    """
    cutoff = timezone.now() - timedelta(minutes=window_minutes)
    completed = AnalysisJob.objects.filter(
        engine=engine,
        status=AnalysisJob.STATUS_COMPLETED,
        completed_at__gte=cutoff,
    ).count()
    return completed / float(window_minutes)


def _eta_for(pending: int, rate_per_min: float) -> str | None:
    """Estimate "time to drain" pending jobs at the current rate.

    Args:
        pending: Pending job count.
        rate_per_min: Completion rate in jobs per minute.

    Returns:
        ``None`` when rate is zero or pending is zero. Otherwise a
        compact string: seconds under a minute, ``Nm`` under an hour,
        ``Xh Ym`` otherwise.
    """
    if pending <= 0 or rate_per_min <= 0:
        return None
    total_seconds = int((pending / rate_per_min) * 60)
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        return f"{total_seconds // 60}m"
    hours, rem = divmod(total_seconds, 3600)
    return f"{hours}h {rem // 60}m"


def _group_recent_by_game(limit: int = 25) -> list[dict[str, Any]]:
    """Group recently completed AnalysisJobs by game and pivot engine → column.

    Pulls the most recent ``limit * 4`` completed jobs (a buffer that
    handles the common 2-engines-per-game case), groups them by
    ``game_id`` in Python, and produces one row per game with separate
    columns for each engine's ``duration_seconds`` plus the latest
    ``completed_at`` and the game's ``slug`` for URL building.

    Args:
        limit: Maximum number of distinct games to return.

    Returns:
        List of dicts with keys ``game_id``, ``game_slug``,
        ``stockfish_seconds``, ``lc0_seconds`` (each ``float | None``),
        ``latest_completed_at``.
    """
    buffer_size = max(limit * 4, 50)
    recent = list(
        AnalysisJob.objects
        .filter(status=AnalysisJob.STATUS_COMPLETED, completed_at__isnull=False)
        .select_related("game")
        .order_by("-completed_at")
        .values(
            "game_id", "game__slug", "engine", "duration_seconds",
            "completed_at",
        )[:buffer_size]
    )

    by_game: dict[str, dict[str, Any]] = {}
    for job in recent:
        gid = str(job["game_id"])
        row = by_game.setdefault(gid, {
            "game_id": gid,
            "game_slug": job["game__slug"],
            "stockfish_seconds": None,
            "lc0_seconds": None,
            "latest_completed_at": job["completed_at"],
        })
        if job["completed_at"] > row["latest_completed_at"]:
            row["latest_completed_at"] = job["completed_at"]
        if job["engine"] == "stockfish":
            row["stockfish_seconds"] = job["duration_seconds"]
        elif job["engine"] == "lc0":
            row["lc0_seconds"] = job["duration_seconds"]

    rows = sorted(by_game.values(), key=lambda r: r["latest_completed_at"], reverse=True)
    return rows[:limit]
