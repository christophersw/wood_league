"""
Title: scheduling.py — pure cron-expression helpers
Description:
    Timezone-aware wrappers over croniter used by Step 0 of the
    reconcile cron (prev_fire) and the scheduling UI (next_runs preview
    + future-planned table). No Django models; pure and unit-testable.
Changelog:
    2026-05-18: _base raises ValueError (not KeyError) for unknown tz.
    2026-05-18: Initial — issue #155 Sub-project B.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from croniter import croniter


def _base(crontab: str, tz: str, anchor: datetime) -> croniter:
    """Return a croniter anchored at ``anchor`` in zone ``tz``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name the expression is evaluated in.
        anchor: reference instant (tz-aware).

    Returns:
        croniter: iterator positioned at ``anchor`` in ``tz``.

    Raises:
        ValueError: if ``crontab`` is invalid or ``tz`` is not a known
            IANA timezone.
    """
    if not croniter.is_valid(crontab):
        raise ValueError(f"invalid cron expression: {crontab!r}")
    try:
        zone = ZoneInfo(tz)
    except KeyError as exc:
        raise ValueError(f"unknown timezone: {tz!r}") from exc
    local = anchor.astimezone(zone)
    return croniter(crontab, local)


def next_runs(
    crontab: str, tz: str, count: int, *, after: datetime | None = None,
) -> list[datetime]:
    """Return the next ``count`` fire times strictly after ``after``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name.
        count: how many upcoming times to return.
        after: instant to start from (tz-aware); defaults to now UTC.

    Returns:
        list[datetime]: ``count`` tz-aware datetimes in ``tz``, ascending.

    Raises:
        ValueError: if ``crontab`` is invalid or ``tz`` is not a known
            IANA timezone.
    """
    anchor = after or datetime.now(ZoneInfo("UTC"))
    it = _base(crontab, tz, anchor)
    return [it.get_next(datetime) for _ in range(count)]


def prev_fire(crontab: str, tz: str, now: datetime) -> datetime:
    """Return the most recent fire time at or before ``now``.

    Args:
        crontab: 5-field cron expression.
        tz: IANA timezone name.
        now: reference instant (tz-aware).

    Returns:
        datetime: the tz-aware previous fire time (in ``tz``).

    Raises:
        ValueError: if ``crontab`` is invalid or ``tz`` is not a known
            IANA timezone.
    """
    it = _base(crontab, tz, now)
    return it.get_prev(datetime)
