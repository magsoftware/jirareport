from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from jirareport.domain.models import DateRange, MonthId, WorklogEntry


def test_month_id_parse_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="Invalid month format"):
        MonthId.parse("202603")


def test_month_id_rejects_invalid_month_number() -> None:
    with pytest.raises(ValueError, match="Month must be in range"):
        MonthId(year=2026, month=13)


def test_previous_month_rolls_back_to_previous_year() -> None:
    assert MonthId(year=2026, month=1).previous_month() == MonthId(year=2025, month=12)


def test_date_range_rejects_invalid_boundaries() -> None:
    with pytest.raises(ValueError, match="DateRange end must not be before start"):
        DateRange(start=date(2026, 3, 2), end=date(2026, 3, 1))


def test_worklog_entry_exposes_started_and_ended_dates() -> None:
    entry = WorklogEntry(
        worklog_id="1",
        issue_key="PRJ-1",
        issue_summary="Night shift",
        author_name="Alice",
        author_account_id=None,
        started_at=datetime(2026, 3, 11, 23, 0, tzinfo=ZoneInfo("Europe/Warsaw")),
        ended_at=datetime(2026, 3, 12, 2, 0, tzinfo=ZoneInfo("Europe/Warsaw")),
        duration_seconds=10800,
    )

    assert entry.started_date == date(2026, 3, 11)
    assert entry.ended_date == date(2026, 3, 12)
    assert entry.crosses_midnight is True
