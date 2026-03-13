from __future__ import annotations

from datetime import datetime
from io import BytesIO

from jirareport.domain.models import (
    DailyRawSnapshot,
    JiraSpace,
    MonthId,
    MonthlyWorklogReport,
    WorklogEntry,
)


def serialize_worklog(
    entry: WorklogEntry,
    snapshot_date: str | None = None,
) -> dict[str, object]:
    """Serializes a normalized worklog entry to JSON-friendly data.

    Args:
        entry: Worklog entry to serialize.
        snapshot_date: Optional snapshot date used by the daily raw payload.

    Returns:
        A JSON-serializable dictionary representing one worklog.
    """
    payload: dict[str, object] = {
        "worklog_id": entry.worklog_id,
        "issue_key": entry.issue_key,
        "summary": entry.issue_summary,
        "author": entry.author_name,
        "author_account_id": entry.author_account_id,
        "started_at": _format_datetime(entry.started_at),
        "ended_at": _format_datetime(entry.ended_at),
        "started_date": entry.started_date.isoformat(),
        "ended_date": entry.ended_date.isoformat(),
        "crosses_midnight": entry.crosses_midnight,
        "duration_seconds": entry.duration_seconds,
        "duration_hours": entry.duration_hours,
        "month": entry.started_at.date().strftime("%Y-%m"),
    }
    if snapshot_date is not None:
        payload["snapshot_date"] = snapshot_date
    return payload


def serialize_monthly_worklogs_parquet(
    space: JiraSpace,
    month: MonthId,
    worklogs: list[WorklogEntry],
) -> bytes:
    """Serializes a flat monthly worklog dataset to Parquet bytes."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            pa.field("space_key", pa.string()),
            pa.field("space_name", pa.string()),
            pa.field("space_slug", pa.string()),
            pa.field("report_month", pa.string()),
            pa.field("worklog_id", pa.string()),
            pa.field("issue_key", pa.string()),
            pa.field("issue_summary", pa.string()),
            pa.field("author_name", pa.string()),
            pa.field("author_account_id", pa.string()),
            pa.field("started_at", pa.string()),
            pa.field("ended_at", pa.string()),
            pa.field("started_date", pa.date32()),
            pa.field("ended_date", pa.date32()),
            pa.field("crosses_midnight", pa.bool_()),
            pa.field("duration_seconds", pa.int64()),
            pa.field("duration_hours", pa.float64()),
        ]
    )
    rows = [
        {
            "space_key": space.key,
            "space_name": space.name,
            "space_slug": space.slug,
            "report_month": month.label(),
            "worklog_id": entry.worklog_id,
            "issue_key": entry.issue_key,
            "issue_summary": entry.issue_summary,
            "author_name": entry.author_name,
            "author_account_id": entry.author_account_id,
            "started_at": _format_datetime(entry.started_at),
            "ended_at": _format_datetime(entry.ended_at),
            "started_date": entry.started_date,
            "ended_date": entry.ended_date,
            "crosses_midnight": entry.crosses_midnight,
            "duration_seconds": entry.duration_seconds,
            "duration_hours": entry.duration_hours,
        }
        for entry in worklogs
    ]
    table = pa.Table.from_pylist(rows, schema=schema)
    buffer = BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    return buffer.getvalue()


def serialize_daily_snapshot(snapshot: DailyRawSnapshot) -> dict[str, object]:
    """Serializes the raw daily snapshot payload.

    Args:
        snapshot: Snapshot built by the main daily use case.

    Returns:
        A JSON-serializable dictionary for the raw daily report.
    """
    snapshot_date = snapshot.snapshot_date.isoformat()
    worklogs = [
        serialize_worklog(entry, snapshot_date=snapshot_date)
        for entry in snapshot.worklogs
    ]
    return {
        "report_type": "daily_raw_snapshot",
        "project_key": snapshot.project_key,
        "space": serialize_space(snapshot.space),
        "snapshot_date": snapshot_date,
        "window_start": snapshot.window.start.isoformat(),
        "window_end": snapshot.window.end.isoformat(),
        "generated_at": _format_datetime(snapshot.generated_at),
        "timezone": snapshot.timezone_name,
        "worklogs": worklogs,
    }


def serialize_monthly_report(report: MonthlyWorklogReport) -> dict[str, object]:
    """Serializes a derived monthly report.

    Args:
        report: Monthly report built from normalized worklogs.

    Returns:
        A JSON-serializable dictionary for the monthly report.
    """
    tickets = []
    for ticket in report.tickets:
        tickets.append(
            {
                "issue_key": ticket.issue_key,
                "summary": ticket.summary,
                "total_duration_hours": ticket.total_duration_hours,
                "bookings": [serialize_worklog(entry) for entry in ticket.bookings],
            }
        )
    return {
        "report_type": "monthly_worklogs",
        "project_key": report.project_key,
        "space": serialize_space(report.space),
        "month": report.month.label(),
        "generated_at": _format_datetime(report.generated_at),
        "timezone": report.timezone_name,
        "tickets": tickets,
    }


def serialize_space(space: JiraSpace) -> dict[str, object]:
    """Serializes Jira space metadata for JSON report payloads."""
    return {
        "key": space.key,
        "name": space.name,
        "slug": space.slug,
        "board_id": space.board_id,
    }


def _format_datetime(value: datetime) -> str:
    """Formats a datetime without fractional seconds for report output."""
    return value.isoformat(timespec="seconds")
