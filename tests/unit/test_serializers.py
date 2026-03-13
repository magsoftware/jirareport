from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from typing import Any, cast
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

from jirareport.application.parquet_serializers import serialize_monthly_worklogs
from jirareport.application.serializers import (
    serialize_daily_snapshot,
)
from jirareport.domain.models import (
    DailyRawSnapshot,
    DateRange,
    JiraSpace,
    MonthId,
    WorklogEntry,
)


def test_serialize_daily_snapshot_omits_fractional_seconds() -> None:
    timezone = ZoneInfo("Europe/Warsaw")
    entry = WorklogEntry(
        worklog_id="1",
        issue_key="PRJ-1",
        issue_summary="Task",
        issue_type="Bug",
        author_name="Alice",
        author_account_id="acc-1",
        started_at=datetime(2026, 3, 11, 9, 13, 12, 163000, tzinfo=timezone),
        ended_at=datetime(2026, 3, 11, 10, 13, 12, 987000, tzinfo=timezone),
        duration_seconds=3600,
    )
    snapshot = DailyRawSnapshot(
        space=JiraSpace(key="PRJ", name="Project", slug="project"),
        snapshot_date=date(2026, 3, 11),
        window=DateRange(start=date(2026, 2, 1), end=date(2026, 3, 11)),
        generated_at=datetime(2026, 3, 11, 19, 39, 4, 465615, tzinfo=timezone),
        timezone_name="Europe/Warsaw",
        worklogs=(entry,),
    )

    payload = serialize_daily_snapshot(snapshot)
    worklogs = cast(list[dict[str, Any]], payload["worklogs"])
    worklog = worklogs[0]

    assert payload["generated_at"] == "2026-03-11T19:39:04+01:00"
    assert payload["space"] == {
        "key": "PRJ",
        "name": "Project",
        "slug": "project",
        "board_id": None,
    }
    assert worklog["started_at"] == "2026-03-11T09:13:12+01:00"
    assert worklog["ended_at"] == "2026-03-11T10:13:12+01:00"
    assert worklog["issue_type"] == "Bug"


def test_serialize_monthly_worklogs_builds_flat_rows() -> None:
    timezone = ZoneInfo("Europe/Warsaw")
    entry = WorklogEntry(
        worklog_id="1",
        issue_key="PRJ-1",
        issue_summary="Task",
        issue_type="Story",
        author_name="Alice",
        author_account_id="acc-1",
        started_at=datetime(2026, 3, 11, 9, 13, 12, tzinfo=timezone),
        ended_at=datetime(2026, 3, 11, 10, 13, 12, tzinfo=timezone),
        duration_seconds=3600,
    )

    payload = serialize_monthly_worklogs(
        JiraSpace(key="PRJ", name="Project", slug="project"),
        MonthId(year=2026, month=3),
        [entry],
    )

    table = pq.read_table(BytesIO(payload))
    row = table.to_pylist()[0]

    assert row["space_key"] == "PRJ"
    assert row["space_slug"] == "project"
    assert row["report_month"] == "2026-03"
    assert row["issue_key"] == "PRJ-1"
    assert row["issue_type"] == "Story"
    assert row["author_name"] == "Alice"
    assert row["duration_hours"] == 1.0
