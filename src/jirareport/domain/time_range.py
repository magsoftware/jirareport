from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from jirareport.domain.models import DateRange, MonthId


def current_date(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def month_range(month: MonthId) -> DateRange:
    start = month.first_day()
    end = month.next_month().first_day() - timedelta(days=1)
    return DateRange(start=start, end=end)


def rolling_window(reference_date: date) -> DateRange:
    previous_month = MonthId.from_date(reference_date).previous_month()
    return DateRange(start=previous_month.first_day(), end=reference_date)


def months_in_range(window: DateRange) -> tuple[MonthId, ...]:
    months: list[MonthId] = []
    current = MonthId.from_date(window.start)
    last = MonthId.from_date(window.end)
    while current <= last:
        months.append(current)
        current = current.next_month()
    return tuple(months)
