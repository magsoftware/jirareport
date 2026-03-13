from __future__ import annotations

from datetime import datetime

from jirareport.domain.models import (
    DailyRawSnapshot,
    JiraSpace,
    MonthlyWorklogReport,
    WorklogEntry,
)
from jirareport.domain.ports import JsonObject, JsonValue


def serialize_worklog(
    entry: WorklogEntry,
    snapshot_date: str | None = None,
) -> JsonObject:
    """Serializes a normalized worklog entry to JSON-friendly data.

    Args:
        entry: Worklog entry to serialize.
        snapshot_date: Optional snapshot date used by the daily raw payload.

    Returns:
        A JSON-serializable dictionary representing one worklog.
    """
    payload: JsonObject = {
        "worklog_id": entry.worklog_id,
        "issue_key": entry.issue_key,
        "summary": entry.issue_summary,
        "issue_type": entry.issue_type,
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


def serialize_daily_snapshot(snapshot: DailyRawSnapshot) -> JsonObject:
    """Serializes the raw daily snapshot payload.

    Args:
        snapshot: Snapshot built by the main daily use case.

    Returns:
        A JSON-serializable dictionary for the raw daily report.
    """
    snapshot_date = snapshot.snapshot_date.isoformat()
    worklogs: list[JsonValue] = [serialize_worklog(entry, snapshot_date=snapshot_date) for entry in snapshot.worklogs]

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


def serialize_monthly_report(report: MonthlyWorklogReport) -> JsonObject:
    """Serializes a derived monthly report.

    Args:
        report: Monthly report built from normalized worklogs.

    Returns:
        A JSON-serializable dictionary for the monthly report.
    """
    tickets: list[JsonValue] = []
    for ticket in report.tickets:
        tickets.append(
            {
                "issue_key": ticket.issue_key,
                "summary": ticket.summary,
                "issue_type": ticket.issue_type,
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


def serialize_space(space: JiraSpace) -> JsonObject:
    """Serializes Jira space metadata for JSON report payloads.

    Args:
        space: Reporting space attached to the current payload.

    Returns:
        A JSON-serializable dictionary with stable space identifiers.
    """
    return {
        "key": space.key,
        "name": space.name,
        "slug": space.slug,
    }


def _format_datetime(value: datetime) -> str:
    """Formats a datetime without fractional seconds for report output.

    Args:
        value: Datetime value emitted into report payloads.

    Returns:
        ISO 8601 datetime string truncated to whole seconds.
    """
    return value.isoformat(timespec="seconds")
