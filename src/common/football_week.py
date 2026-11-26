from __future__ import annotations

from datetime import datetime, timedelta

from common.timezone import get_local_timezone

# Python weekday: Monday=0 ... Sunday=6
WEDNESDAY = 2
THURSDAY = 3
MONDAY = 0
TUESDAY = 1


def week_date_range(
    *,
    hold_until_weekday: int,
    now=None,
    start_weekday: int = THURSDAY,
):
    """
    Local football week, held through the given weekday night.

    CFB starts Thursday and holds through Monday night.
    NFL starts Wednesday so a Wednesday kickoff stays on the slate,
    and holds finished games through Tuesday night.
    """
    if now is None:
        local = datetime.now(get_local_timezone())
    elif now.tzinfo is None:
        local = now.replace(tzinfo=get_local_timezone())
    else:
        local = now.astimezone(get_local_timezone())

    days_since_start = (local.weekday() - start_weekday) % 7
    week_start = (local - timedelta(days=days_since_start)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    days_held = (hold_until_weekday - start_weekday) % 7
    hold_end = week_start + timedelta(days=days_held + 1)

    if local >= hold_end:
        week_start += timedelta(days=7)
        hold_end = week_start + timedelta(days=days_held + 1)

    start_date = week_start.date()
    end_date = (hold_end - timedelta(seconds=1)).date()
    return start_date, end_date


def date_span(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)
