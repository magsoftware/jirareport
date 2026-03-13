from __future__ import annotations

from datetime import date

from jirareport.domain.models import DateRange, MonthId
from jirareport.domain.time_range import (
    active_months,
    current_date,
    explicit_range,
    month_range,
    months_in_range,
    rolling_window,
)


def test_month_range_returns_full_calendar_month() -> None:
    result = month_range(MonthId(year=2026, month=3))

    assert result.start == date(2026, 3, 1)
    assert result.end == date(2026, 3, 31)


def test_rolling_window_starts_at_previous_month_boundary() -> None:
    result = rolling_window(date(2026, 3, 11))

    assert result == DateRange(start=date(2026, 2, 1), end=date(2026, 3, 11))


def test_rolling_window_uses_two_closed_months_on_first_day_of_month() -> None:
    result = rolling_window(date(2026, 4, 1))

    assert result == DateRange(start=date(2026, 2, 1), end=date(2026, 3, 31))


def test_active_months_returns_closed_months_on_first_day_of_month() -> None:
    assert active_months(date(2026, 4, 1)) == (
        MonthId(year=2026, month=2),
        MonthId(year=2026, month=3),
    )


def test_active_months_returns_previous_and_current_month_otherwise() -> None:
    assert active_months(date(2026, 4, 2)) == (
        MonthId(year=2026, month=3),
        MonthId(year=2026, month=4),
    )


def test_months_in_range_handles_year_boundary() -> None:
    window = DateRange(start=date(2025, 12, 15), end=date(2026, 2, 2))

    assert months_in_range(window) == (
        MonthId(year=2025, month=12),
        MonthId(year=2026, month=1),
        MonthId(year=2026, month=2),
    )


def test_current_date_returns_date_instance() -> None:
    assert isinstance(current_date("Europe/Warsaw"), date)


def test_explicit_range_returns_inclusive_user_range() -> None:
    assert explicit_range(date(2025, 1, 1), date(2025, 12, 31)) == DateRange(
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )
