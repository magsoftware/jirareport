from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pyarrow as pa
import pyarrow.parquet as pq

from jirareport.domain.models import JiraSpace, MonthId, WorklogEntry

MONTHLY_WORKLOG_SCHEMA = pa.schema(
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


def serialize_monthly_worklogs(
    space: JiraSpace,
    month: MonthId,
    worklogs: list[WorklogEntry],
) -> bytes:
    """Serializes a flat monthly worklog dataset to Parquet bytes."""
    table = pa.Table.from_pylist(
        [
            _monthly_worklog_row(space, month, entry)
            for entry in worklogs
        ],
        schema=MONTHLY_WORKLOG_SCHEMA,
    )
    buffer = BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    return buffer.getvalue()


def _monthly_worklog_row(
    space: JiraSpace,
    month: MonthId,
    entry: WorklogEntry,
) -> dict[str, object]:
    """Builds one flat monthly worklog row used by Parquet export."""
    return {
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


def _format_datetime(value: datetime) -> str:
    """Formats datetime-like values without fractional seconds for Parquet export."""
    return value.isoformat(timespec="seconds")
