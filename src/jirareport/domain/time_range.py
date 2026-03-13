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
    """Builds the operational reporting window for the nightly flow.

    Most days the window covers the current and previous month, ending on the
    reference date itself. On the first day of a month the run is used to
    close the previous month, so the window shifts back by one month and ends
    on the last day of the previous month.
    """
    current_month = MonthId.from_date(reference_date)
    if reference_date.day == 1:
        start_month = current_month.previous_month().previous_month()
        return DateRange(
            start=start_month.first_day(),
            end=reference_date - timedelta(days=1),
        )
    previous_month = current_month.previous_month()
    return DateRange(start=previous_month.first_day(), end=reference_date)


def active_months(reference_date: date) -> tuple[MonthId, MonthId]:
    """Returns the two active reporting months for the reference date."""
    months = months_in_range(rolling_window(reference_date))
    if len(months) != 2:
        raise ValueError("Operational reporting window must span exactly two months.")
    return months


def explicit_range(start: date, end: date) -> DateRange:
    """Builds an explicit user-requested date range for backfills."""
    return DateRange(start=start, end=end)


def months_in_range(window: DateRange) -> tuple[MonthId, ...]:
    """Returns all months touched by the provided date range."""
    months: list[MonthId] = []
    current = MonthId.from_date(window.start)
    last = MonthId.from_date(window.end)
    while current <= last:
        months.append(current)
        current = current.next_month()
    return tuple(months)
