from __future__ import annotations

from jirareport.domain.models import (
    DailyRawSnapshot,
    MonthId,
    SheetCellValue,
    SpreadsheetPublishRequest,
    WorklogEntry,
    WorksheetData,
)
from jirareport.domain.time_range import months_in_range

MONTHLY_RAW_HEADERS = (
    "snapshot_date",
    "window_start",
    "window_end",
    "generated_at",
    "timezone",
    "month",
    "issue_key",
    "summary",
    "author",
    "author_account_id",
    "worklog_id",
    "started_at",
    "ended_at",
    "started_date",
    "ended_date",
    "crosses_midnight",
    "duration_seconds",
    "duration_hours",
)


def build_spreadsheet_request(
    snapshot: DailyRawSnapshot,
    spreadsheet_id: str,
    year: int,
) -> SpreadsheetPublishRequest:
    """Builds the yearly spreadsheet payload for active monthly raw worksheets."""
    worksheets = tuple(
        WorksheetData(
            title=_worksheet_title(month),
            rows=_with_header(
                MONTHLY_RAW_HEADERS,
                _build_monthly_raw_rows(snapshot, month),
            ),
        )
        for month in _months_for_year(snapshot, year)
    )
    return SpreadsheetPublishRequest(
        year=year,
        spreadsheet_id=spreadsheet_id,
        worksheets=worksheets,
    )


def years_for_snapshot(snapshot: DailyRawSnapshot) -> tuple[int, ...]:
    """Returns all calendar years touched by the active reporting months."""
    years = {
        month.year
        for month in months_in_range(snapshot.window)
    }
    return tuple(sorted(years))


def _months_for_year(
    snapshot: DailyRawSnapshot,
    year: int,
) -> tuple[MonthId, ...]:
    """Returns active reporting months that belong to the requested spreadsheet year."""
    return tuple(
        month
        for month in months_in_range(snapshot.window)
        if month.year == year
    )


def _worksheet_title(month: MonthId) -> str:
    """Returns the worksheet title used for one monthly raw data tab."""
    return f"{month.month:02d}"


def _build_monthly_raw_rows(
    snapshot: DailyRawSnapshot,
    month: MonthId,
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Builds flat raw worklog rows for one calendar month worksheet."""
    snapshot_date = snapshot.snapshot_date.isoformat()
    window_start = snapshot.window.start.isoformat()
    window_end = snapshot.window.end.isoformat()
    generated_at = snapshot.generated_at.isoformat(timespec="seconds")
    worklogs = _worklogs_for_month(snapshot.worklogs, month)
    rows = [
        _raw_row(
            entry,
            snapshot_date,
            window_start,
            window_end,
            generated_at,
            snapshot.timezone_name,
        )
        for entry in worklogs
    ]
    return tuple(rows)


def _worklogs_for_month(
    worklogs: tuple[WorklogEntry, ...],
    month: MonthId,
) -> list[WorklogEntry]:
    """Returns worklogs whose local start date belongs to the requested month."""
    relevant = [entry for entry in worklogs if month.contains(entry.started_date)]
    return sorted(
        relevant,
        key=lambda item: (
            item.started_at,
            item.issue_key,
            item.author_name,
            item.worklog_id,
        ),
    )


def _raw_row(
    entry: WorklogEntry,
    snapshot_date: str,
    window_start: str,
    window_end: str,
    generated_at: str,
    timezone_name: str,
) -> tuple[SheetCellValue, ...]:
    """Converts one worklog entry to the monthly raw worksheet row format."""
    return (
        snapshot_date,
        window_start,
        window_end,
        generated_at,
        timezone_name,
        entry.started_at.strftime("%Y-%m"),
        entry.issue_key,
        entry.issue_summary,
        entry.author_name,
        entry.author_account_id or "",
        entry.worklog_id,
        entry.started_at.isoformat(timespec="seconds"),
        entry.ended_at.isoformat(timespec="seconds"),
        entry.started_date.isoformat(),
        entry.ended_date.isoformat(),
        _sheet_boolean(entry.crosses_midnight),
        entry.duration_seconds,
        entry.duration_hours,
    )


def _with_header(
    header: tuple[str, ...],
    rows: tuple[tuple[SheetCellValue, ...], ...],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Prepends a header row to a worksheet payload."""
    return (header, *rows)


def _sheet_boolean(value: bool) -> str:
    """Serializes a boolean value in a spreadsheet-friendly form."""
    return "TRUE" if value else "FALSE"
