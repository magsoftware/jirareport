from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import cast

from jirareport.domain.models import (
    DailyRawSnapshot,
    SheetCellValue,
    SpreadsheetPublishRequest,
    WorklogEntry,
    WorksheetData,
)

RAW_WORKLOGS_TAB = "raw_worklogs"
MONTHLY_SUMMARY_TAB = "monthly_summary"
DAILY_SUMMARY_TAB = "daily_summary"
METADATA_TAB = "metadata"

RAW_HEADERS = (
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
MONTHLY_HEADERS = (
    "month",
    "issue_key",
    "summary",
    "author",
    "author_account_id",
    "entries_count",
    "total_seconds",
    "total_hours",
)
DAILY_HEADERS = (
    "date",
    "month",
    "issue_key",
    "summary",
    "author",
    "author_account_id",
    "entries_count",
    "total_seconds",
    "total_hours",
)
METADATA_HEADERS = (
    "space_key",
    "space_name",
    "space_slug",
    "spreadsheet_year",
    "last_run_at",
    "source_snapshot_date",
    "window_start",
    "window_end",
    "timezone",
    "raw_rows_count",
    "monthly_summary_rows_count",
    "daily_summary_rows_count",
)


def build_spreadsheet_request(
    snapshot: DailyRawSnapshot,
    spreadsheet_id: str,
    year: int,
) -> SpreadsheetPublishRequest:
    """Builds a full yearly spreadsheet payload from one daily snapshot."""
    worklogs = _worklogs_for_year(snapshot.worklogs, year)
    raw_rows = _build_raw_rows(snapshot, worklogs)
    monthly_rows = _build_monthly_rows(worklogs)
    daily_rows = _build_daily_rows(worklogs)
    metadata_rows = _build_metadata_rows(
        snapshot,
        year,
        raw_rows,
        monthly_rows,
        daily_rows,
    )
    worksheets = (
        WorksheetData(RAW_WORKLOGS_TAB, _with_header(RAW_HEADERS, raw_rows)),
        WorksheetData(
            MONTHLY_SUMMARY_TAB,
            _with_summary_footer(MONTHLY_HEADERS, monthly_rows, "F", "G", "H"),
        ),
        WorksheetData(
            DAILY_SUMMARY_TAB,
            _with_summary_footer(DAILY_HEADERS, daily_rows, "G", "H", "I"),
        ),
        WorksheetData(METADATA_TAB, _with_header(METADATA_HEADERS, metadata_rows)),
    )
    return SpreadsheetPublishRequest(
        year=year,
        spreadsheet_id=spreadsheet_id,
        worksheets=worksheets,
    )


def years_for_snapshot(snapshot: DailyRawSnapshot) -> tuple[int, ...]:
    """Returns all calendar years touched by the snapshot reporting window."""
    years = range(snapshot.window.start.year, snapshot.window.end.year + 1)
    return tuple(years)


def _worklogs_for_year(
    worklogs: tuple[WorklogEntry, ...],
    year: int,
) -> list[WorklogEntry]:
    """Returns worklogs whose local start date belongs to the requested year."""
    relevant = [entry for entry in worklogs if entry.started_date.year == year]
    return sorted(
        relevant,
        key=lambda item: (
            item.started_at,
            item.issue_key,
            item.author_name,
            item.worklog_id,
        ),
    )


def _build_raw_rows(
    snapshot: DailyRawSnapshot,
    worklogs: list[WorklogEntry],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Builds flat raw worklog rows for one yearly spreadsheet."""
    snapshot_date = snapshot.snapshot_date.isoformat()
    window_start = snapshot.window.start.isoformat()
    window_end = snapshot.window.end.isoformat()
    generated_at = snapshot.generated_at.isoformat(timespec="seconds")
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


def _raw_row(
    entry: WorklogEntry,
    snapshot_date: str,
    window_start: str,
    window_end: str,
    generated_at: str,
    timezone_name: str,
) -> tuple[SheetCellValue, ...]:
    """Converts one worklog entry to the raw tab row format."""
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


def _build_monthly_rows(
    worklogs: list[WorklogEntry],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Builds monthly aggregate rows for one yearly spreadsheet."""
    groups = _group_worklogs(
        worklogs,
        lambda entry: (
            entry.started_at.strftime("%Y-%m"),
            entry.issue_key,
            entry.issue_summary,
            entry.author_name,
            entry.author_account_id or "",
        ),
    )
    rows: list[tuple[SheetCellValue, ...]] = []
    for key, entries in groups:
        month, issue_key, summary, author, author_account_id = cast(
            tuple[str, str, str, str, str],
            key,
        )
        rows.append(
            (
                month,
                issue_key,
                summary,
                author,
                author_account_id,
                len(entries),
                _total_seconds(entries),
                _total_hours(entries),
            )
        )
    return tuple(rows)


def _build_daily_rows(
    worklogs: list[WorklogEntry],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Builds daily aggregate rows for one yearly spreadsheet."""
    groups = _group_worklogs(
        worklogs,
        lambda entry: (
            entry.started_date.isoformat(),
            entry.started_at.strftime("%Y-%m"),
            entry.issue_key,
            entry.issue_summary,
            entry.author_name,
            entry.author_account_id or "",
        ),
    )
    rows: list[tuple[SheetCellValue, ...]] = []
    for key, entries in groups:
        day, month, issue_key, summary, author, author_account_id = cast(
            tuple[str, str, str, str, str, str],
            key,
        )
        rows.append(
            (
                day,
                month,
                issue_key,
                summary,
                author,
                author_account_id,
                len(entries),
                _total_seconds(entries),
                _total_hours(entries),
            )
        )
    return tuple(rows)


def _group_worklogs(
    worklogs: list[WorklogEntry],
    key_builder: Callable[[WorklogEntry], tuple[object, ...]],
) -> list[tuple[tuple[object, ...], list[WorklogEntry]]]:
    """Groups worklogs by the provided key builder and returns sorted items."""
    grouped: dict[tuple[object, ...], list[WorklogEntry]] = {}
    for entry in worklogs:
        key = key_builder(entry)
        grouped.setdefault(key, []).append(entry)
    return sorted(grouped.items(), key=lambda item: item[0])


def _build_metadata_rows(
    snapshot: DailyRawSnapshot,
    year: int,
    raw_rows: tuple[tuple[SheetCellValue, ...], ...],
    monthly_rows: tuple[tuple[SheetCellValue, ...], ...],
    daily_rows: tuple[tuple[SheetCellValue, ...], ...],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Builds the metadata tab rows for one yearly spreadsheet."""
    row = (
        snapshot.space.key,
        snapshot.space.name,
        snapshot.space.slug,
        year,
        snapshot.generated_at.isoformat(timespec="seconds"),
        snapshot.snapshot_date.isoformat(),
        snapshot.window.start.isoformat(),
        snapshot.window.end.isoformat(),
        snapshot.timezone_name,
        len(raw_rows),
        len(monthly_rows),
        len(daily_rows),
    )
    return (row,)


def _total_seconds(worklogs: Iterable[WorklogEntry]) -> int:
    """Returns the total duration in seconds for a collection of worklogs."""
    return sum(entry.duration_seconds for entry in worklogs)


def _total_hours(worklogs: Iterable[WorklogEntry]) -> float:
    """Returns the total duration in hours for a collection of worklogs."""
    return round(_total_seconds(worklogs) / 3600, 2)


def _with_header(
    header: tuple[str, ...],
    rows: tuple[tuple[SheetCellValue, ...], ...],
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Prepends a header row to a worksheet payload."""
    return (header, *rows)


def _with_summary_footer(
    header: tuple[str, ...],
    rows: tuple[tuple[SheetCellValue, ...], ...],
    entries_column: str,
    seconds_column: str,
    hours_column: str,
) -> tuple[tuple[SheetCellValue, ...], ...]:
    """Prepends the header and appends a subtotal row for filtered views."""
    data = _with_header(header, rows)
    data_start_row = 2
    data_end_row = len(rows) + 1
    footer = _summary_footer_row(
        len(header),
        data_start_row,
        data_end_row,
        entries_column,
        seconds_column,
        hours_column,
    )
    return (*data, footer)


def _summary_footer_row(
    width: int,
    data_start_row: int,
    data_end_row: int,
    entries_column: str,
    seconds_column: str,
    hours_column: str,
) -> tuple[SheetCellValue, ...]:
    """Builds the subtotal row appended to summary worksheets."""
    cells: list[SheetCellValue] = ["" for _ in range(width)]
    cells[0] = "VISIBLE_TOTALS"
    cells[_column_to_index(entries_column)] = _subtotal_formula(
        entries_column,
        data_start_row,
        data_end_row,
    )
    cells[_column_to_index(seconds_column)] = _subtotal_formula(
        seconds_column,
        data_start_row,
        data_end_row,
    )
    cells[_column_to_index(hours_column)] = _subtotal_formula(
        hours_column,
        data_start_row,
        data_end_row,
    )
    return tuple(cells)


def _subtotal_formula(column: str, start_row: int, end_row: int) -> str:
    """Builds a Google Sheets subtotal formula for one numeric column."""
    return f"=SUBTOTAL(109,{column}{start_row}:{column}{end_row})"


def _column_to_index(column: str) -> int:
    """Converts a spreadsheet column label like 'A' to a zero-based index."""
    return ord(column) - ord("A")


def _sheet_boolean(value: bool) -> str:
    """Serializes a boolean value in a spreadsheet-friendly form."""
    return "TRUE" if value else "FALSE"
