"""Integration scenarios for the BigQuery warehouse adapter.

Goal
- Validate the real BigQuery adapter against a stateful in-memory fake client.
- Prove that monthly loads, reruns, schema migration, and reporting views behave
  correctly without requiring access to a live BigQuery dataset.

Fixtures
- `StatefulFakeBigQueryClient` stores created tables, loaded rows, executed SQL,
  and view definitions exactly as the adapter manipulates them.
- Real `BigQueryWorklogWarehouse` is used so the tests exercise adapter logic
  rather than reimplementing it.
- Parquet payloads are produced by the production serializer to keep the
  warehouse input format realistic.

Scenarios
1. The first monthly sync creates the `worklogs` table, ensures the `issue_type`
   column, loads rows, and builds both `all_*` and per-space views.
2. Re-running the same space/month slice replaces existing rows instead of
   appending duplicates, which models idempotent backfill behavior.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from jirareport.application.parquet_serializers import serialize_monthly_worklogs
from jirareport.domain.models import JiraSpace, MonthId, WorklogEntry
from jirareport.infrastructure.google.bigquery_client import BigQueryWorklogWarehouse
from tests.fakes.fake_bigquery import StatefulFakeBigQueryClient


def test_warehouse_creates_table_loads_rows_and_builds_reporting_views() -> None:
    """Scenario
    Given a fresh fake BigQuery environment and one curated monthly payload
    When the warehouse loads the month and refreshes views
    Then the worklogs table, schema migration, loaded rows, and per-space views
    are all present in fake BigQuery state.
    """

    client = StatefulFakeBigQueryClient()
    click_price = JiraSpace(key="LA004832", name="Click Price", slug="click-price")
    data_fixer = JiraSpace(key="LA009644", name="Data Fixer", slug="data-fixer")
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(click_price, data_fixer),
        client_factory=lambda: client,
    )
    payload = serialize_monthly_worklogs(
        click_price,
        MonthId(year=2026, month=3),
        [_worklog("wl-1", "LA004832-1", "Bug", "Alice", "2026-03-05T09:00:00+01:00")],
    )

    warehouse.load_monthly_worklogs(click_price, MonthId(year=2026, month=3), payload)
    warehouse.ensure_views()

    rows = client.table_rows("jira-report-489919.jirareport.worklogs")
    assert rows == [
        {
            "space_key": "LA004832",
            "space_name": "Click Price",
            "space_slug": "click-price",
            "report_month": "2026-03",
            "worklog_id": "wl-1",
            "issue_key": "LA004832-1",
            "issue_summary": "Work item",
            "issue_type": "Bug",
            "author_name": "Alice",
            "author_account_id": "alice-1",
            "started_at": "2026-03-05T09:00:00+01:00",
            "ended_at": "2026-03-05T10:00:00+01:00",
            "started_date": rows[0]["started_date"],
            "ended_date": rows[0]["ended_date"],
            "crosses_midnight": False,
            "duration_seconds": 3600,
            "duration_hours": 1.0,
        }
    ]
    schema = client.tables["jira-report-489919.jirareport.worklogs"].schema_fields
    assert "issue_type" in schema
    assert (
        "ALTER TABLE `jira-report-489919.jirareport.worklogs` "
        "ADD COLUMN IF NOT EXISTS issue_type STRING"
    ) in client.queries
    assert "jira-report-489919.jirareport.all_spaces_by_issue" in client.views
    assert "jira-report-489919.jirareport.click_price_by_issue" in client.views
    assert "jira-report-489919.jirareport.data_fixer_by_issue" in client.views


def test_warehouse_rerun_replaces_existing_month_slice() -> None:
    """Scenario
    Given one already loaded space/month slice in fake BigQuery
    When the same month is loaded again with different worklog rows
    Then the warehouse deletes the previous slice first and the table ends with
    only the latest rows for that month.
    """

    client = StatefulFakeBigQueryClient()
    click_price = JiraSpace(key="LA004832", name="Click Price", slug="click-price")
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(click_price,),
        client_factory=lambda: client,
    )
    first_payload = serialize_monthly_worklogs(
        click_price,
        MonthId(year=2026, month=3),
        [_worklog("wl-1", "LA004832-1", "Task", "Alice", "2026-03-05T09:00:00+01:00")],
    )
    second_payload = serialize_monthly_worklogs(
        click_price,
        MonthId(year=2026, month=3),
        [_worklog("wl-2", "LA004832-2", "Story", "Bob", "2026-03-06T09:00:00+01:00")],
    )

    warehouse.load_monthly_worklogs(click_price, MonthId(year=2026, month=3), first_payload)
    warehouse.load_monthly_worklogs(click_price, MonthId(year=2026, month=3), second_payload)

    rows = client.table_rows("jira-report-489919.jirareport.worklogs")
    assert [row["worklog_id"] for row in rows] == ["wl-2"]
    assert [row["issue_type"] for row in rows] == ["Story"]


def _worklog(
    worklog_id: str,
    issue_key: str,
    issue_type: str,
    author_name: str,
    started_at: str,
) -> WorklogEntry:
    timezone = ZoneInfo("Europe/Warsaw")
    started = datetime.fromisoformat(started_at).astimezone(timezone)
    return WorklogEntry(
        worklog_id=worklog_id,
        issue_key=issue_key,
        issue_summary="Work item",
        issue_type=issue_type,
        author_name=author_name,
        author_account_id=f"{author_name.lower()}-1",
        started_at=started,
        ended_at=started.replace(hour=started.hour + 1),
        duration_seconds=3600,
    )
