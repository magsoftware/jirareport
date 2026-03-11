from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jirareport.domain.models import DateRange, MonthId


def current_date(timezone_name: str) -> date:
    """Returns the current date in the configured reporting timezone."""
    return datetime.now(ZoneInfo(timezone_name)).date()


def month_range(month: MonthId) -> DateRange:
    """Builds the full inclusive date range for a month."""
    start = month.first_day()
    end = month.next_month().first_day() - timedelta(days=1)
    return DateRange(start=start, end=end)


def rolling_window(reference_date: date) -> DateRange:
    """Builds the rolling daily reporting window.

    The main daily use case uses this range so that delayed or corrected
    worklogs from the previous month are still included.
    """
    previous_month = MonthId.from_date(reference_date).previous_month()
    return DateRange(start=previous_month.first_day(), end=reference_date)


def months_in_range(window: DateRange) -> tuple[MonthId, ...]:
    """Returns all months touched by the provided date range."""
    months: list[MonthId] = []
    current = MonthId.from_date(window.start)
    last = MonthId.from_date(window.end)
    while current <= last:
        months.append(current)
        current = current.next_month()
    return tuple(months)
