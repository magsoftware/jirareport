"""Integration scenarios for the end-to-end reporting pipeline.

Goal
- Exercise the real reporting services together with in-memory storage and
  stateful fake BigQuery/Sheets backends.
- Verify that raw snapshots, curated Parquet datasets, analytical sync, and
  Google Sheets publishing stay consistent across multiple spaces and ranges.

Fixtures
- `InMemoryJsonReportStorage` and `InMemoryCuratedDatasetStorage` mirror the
  production storage split while keeping JSON reports and Parquet datasets in
  memory for direct assertions.
- `FakeWorklogSource` returns deterministic worklogs for the requested window
  while recording every requested date range.
- `StatefulFakeBigQueryClient` and `StatefulFakeSheetsService` simulate the two
  external publishing backends with persistent state.

Scenarios
1. A daily operational run for two spaces writes raw and curated outputs and
   loads both spaces into a shared BigQuery `worklogs` table with per-space
   views.
2. A historical backfill range publishes monthly raw worksheets to the correct
   yearly spreadsheets for each space.
3. The `issue_type` field survives the full path from source worklogs to raw
   JSON, Parquet, BigQuery rows, and Google Sheets worksheets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Any, cast

import pyarrow.parquet as pq

from jirareport.application.services import (
    BackfillService,
    BigQuerySyncService,
    DailySnapshotService,
    SheetsSyncService,
)
from jirareport.domain.models import DateRange, JiraSpace, WorklogEntry
from jirareport.infrastructure.google.bigquery_client import BigQueryWorklogWarehouse
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
    SheetsServiceProtocol,
)
from tests.fakes.fake_bigquery import StatefulFakeBigQueryClient
from tests.fakes.fake_sheets import StatefulFakeSheetsService


@dataclass
class InMemoryJsonReportStorage:
    """Stores JSON report payloads entirely in memory for integration scenarios."""

    json_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)

    def write_json(self, path: str, payload: dict[str, Any]) -> str:
        self.json_payloads[path] = payload
        return path


@dataclass
class InMemoryCuratedDatasetStorage:
    """Stores curated Parquet datasets entirely in memory for integration scenarios."""

    binary_payloads: dict[str, bytes] = field(default_factory=dict)

    def write_parquet(self, path: str, payload: bytes) -> str:
        self.binary_payloads[path] = payload
        return path

    def read_bytes(self, path: str) -> bytes:
        return self.binary_payloads[path]


class FakeWorklogSource:
    """Provides deterministic worklogs filtered by the requested date range."""

    def __init__(self, worklogs: list[WorklogEntry]) -> None:
        self._worklogs = worklogs
        self.windows: list[DateRange] = []

    def fetch_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        self.windows.append(window)
        return [entry for entry in self._worklogs if window.contains(entry.started_date)]


def test_daily_pipeline_syncs_two_spaces_into_shared_bigquery(
    make_worklog: Callable[..., WorklogEntry],
) -> None:
    """Scenario
    Given daily worklogs for Click Price and Data Fixer across active months
    When daily snapshots are generated and both spaces are synced to BigQuery
    Then raw outputs, curated Parquet datasets, shared worklogs rows, and
    per-space analytical views all exist consistently.
    """

    report_storage = InMemoryJsonReportStorage()
    dataset_storage = InMemoryCuratedDatasetStorage()
    click_price = JiraSpace(key="LA004832", name="Click Price", slug="click-price")
    data_fixer = JiraSpace(key="LA009644", name="Data Fixer", slug="data-fixer")
    click_price_source = FakeWorklogSource(
        [
            make_worklog(
                "cp-feb-1",
                "LA004832-1",
                "February bug",
                "Alice",
                "2026-02-20T09:00:00+01:00",
                3600,
                "alice-1",
                "Bug",
            ),
            make_worklog(
                "cp-mar-1",
                "LA004832-2",
                "March story",
                "Alice",
                "2026-03-10T09:00:00+01:00",
                7200,
                "alice-1",
                "Story",
            ),
        ]
    )
    data_fixer_source = FakeWorklogSource(
        [
            make_worklog(
                "df-mar-1",
                "LA009644-1",
                "March task",
                "Bob",
                "2026-03-09T09:00:00+01:00",
                1800,
                "bob-1",
                "Task",
            )
        ]
    )
    daily_date = date(2026, 3, 11)
    DailySnapshotService(
        click_price_source,
        report_storage,
        dataset_storage,
        click_price,
        "Europe/Warsaw",
    ).generate(daily_date)
    DailySnapshotService(
        data_fixer_source,
        report_storage,
        dataset_storage,
        data_fixer,
        "Europe/Warsaw",
    ).generate(daily_date)

    bigquery_client = StatefulFakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(click_price, data_fixer),
        client_factory=lambda: bigquery_client,
    )
    BigQuerySyncService(dataset_storage, warehouse, click_price).generate(daily_date)
    BigQuerySyncService(dataset_storage, warehouse, data_fixer).generate(daily_date)

    rows = bigquery_client.table_rows("jira-report-489919.jirareport.worklogs")
    assert {row["space_slug"] for row in rows} == {"click-price", "data-fixer"}
    assert {row["issue_type"] for row in rows} == {"Bug", "Story", "Task"}
    assert "jira-report-489919.jirareport.click_price_by_issue" in bigquery_client.views
    assert "jira-report-489919.jirareport.data_fixer_by_issue" in bigquery_client.views
    assert click_price_source.windows == [DateRange(start=date(2026, 2, 1), end=daily_date)]
    assert data_fixer_source.windows == [DateRange(start=date(2026, 2, 1), end=daily_date)]


def test_backfill_pipeline_publishes_monthly_sheets_for_each_space(
    make_worklog: Callable[..., WorklogEntry],
) -> None:
    """Scenario
    Given a historical range covering two months in 2025 for two spaces
    When backfill generation is followed by Google Sheets range sync
    Then each configured yearly spreadsheet receives the expected monthly tabs
    with the corresponding raw worklog rows.
    """

    click_price = JiraSpace(key="LA004832", name="Click Price", slug="click-price")
    data_fixer = JiraSpace(key="LA009644", name="Data Fixer", slug="data-fixer")
    window = DateRange(start=date(2025, 1, 1), end=date(2025, 2, 28))
    report_storage = InMemoryJsonReportStorage()
    dataset_storage = InMemoryCuratedDatasetStorage()
    service = StatefulFakeSheetsService()
    service.add_spreadsheet("cp-2025", title="CP 2025")
    service.add_spreadsheet("df-2025", title="DF 2025")
    publisher = GoogleSheetsPublisher(
        service_factory=lambda: cast(SheetsServiceProtocol, service)
    )
    click_price_resolver = GoogleSheetsResolver(
        spreadsheet_ids={2025: "cp-2025"},
        title_prefix="CP",
        service_factory=lambda: cast(SheetsServiceProtocol, service),
    )
    data_fixer_resolver = GoogleSheetsResolver(
        spreadsheet_ids={2025: "df-2025"},
        title_prefix="DF",
        service_factory=lambda: cast(SheetsServiceProtocol, service),
    )
    click_price_source = FakeWorklogSource(
        [
            make_worklog(
                "cp-jan-1",
                "LA004832-1",
                "January bug",
                "Alice",
                "2025-01-15T09:00:00+01:00",
                3600,
                "alice-1",
                "Bug",
            ),
            make_worklog(
                "cp-feb-1",
                "LA004832-2",
                "February task",
                "Alice",
                "2025-02-10T09:00:00+01:00",
                7200,
                "alice-1",
                "Task",
            ),
        ]
    )
    data_fixer_source = FakeWorklogSource(
        [
            make_worklog(
                "df-feb-1",
                "LA009644-1",
                "February story",
                "Bob",
                "2025-02-07T09:00:00+01:00",
                1800,
                "bob-1",
                "Story",
            )
        ]
    )

    BackfillService(
        click_price_source,
        report_storage,
        dataset_storage,
        click_price,
        "Europe/Warsaw",
    ).generate(window)
    BackfillService(
        data_fixer_source,
        report_storage,
        dataset_storage,
        data_fixer,
        "Europe/Warsaw",
    ).generate(window)
    SheetsSyncService(
        click_price_source,
        publisher,
        click_price_resolver,
        click_price,
        "Europe/Warsaw",
    ).generate_range(window)
    SheetsSyncService(
        data_fixer_source,
        publisher,
        data_fixer_resolver,
        data_fixer,
        "Europe/Warsaw",
    ).generate_range(window)

    assert tuple(service.spreadsheets_state["cp-2025"].sheet_ids) == ("01", "02")
    assert tuple(service.spreadsheets_state["df-2025"].sheet_ids) == ("01", "02")
    assert service.worksheet_rows("cp-2025", "01")[1][6] == "LA004832-1"
    assert service.worksheet_rows("cp-2025", "02")[1][6] == "LA004832-2"
    assert service.worksheet_rows("df-2025", "02")[1][6] == "LA009644-1"


def test_issue_type_flows_from_source_to_all_publish_targets(
    make_worklog: Callable[..., WorklogEntry],
) -> None:
    """Scenario
    Given worklogs with distinct Jira issue types in one reporting space
    When daily generation, BigQuery sync, and Google Sheets sync all run
    Then the `issue_type` field is preserved in raw JSON, Parquet, BigQuery
    rows, and worksheet output.
    """

    click_price = JiraSpace(key="LA004832", name="Click Price", slug="click-price")
    report_storage = InMemoryJsonReportStorage()
    dataset_storage = InMemoryCuratedDatasetStorage()
    service = StatefulFakeSheetsService()
    service.add_spreadsheet("cp-2026", title="CP 2026")
    source = FakeWorklogSource(
        [
            make_worklog(
                "cp-mar-1",
                "LA004832-1",
                "March bug",
                "Alice",
                "2026-03-10T09:00:00+01:00",
                3600,
                "alice-1",
                "Bug",
            ),
            make_worklog(
                "cp-mar-2",
                "LA004832-2",
                "March story",
                "Bob",
                "2026-03-11T09:00:00+01:00",
                3600,
                "bob-1",
                "Story",
            ),
        ]
    )
    daily_date = date(2026, 3, 11)
    result = DailySnapshotService(
        source,
        report_storage,
        dataset_storage,
        click_price,
        "Europe/Warsaw",
    ).generate(daily_date)

    bigquery_client = StatefulFakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(click_price,),
        client_factory=lambda: bigquery_client,
    )
    BigQuerySyncService(dataset_storage, warehouse, click_price).generate(daily_date)
    SheetsSyncService(
        source,
        GoogleSheetsPublisher(
            service_factory=lambda: cast(SheetsServiceProtocol, service)
        ),
        GoogleSheetsResolver(
            spreadsheet_ids={2026: "cp-2026"},
            title_prefix="CP",
            service_factory=lambda: cast(SheetsServiceProtocol, service),
        ),
        click_price,
        "Europe/Warsaw",
    ).generate(daily_date)

    raw_issue_types = [
        item["issue_type"]
        for item in report_storage.json_payloads[result.snapshot_path]["worklogs"]
    ]
    parquet_rows = pq.read_table(
        BytesIO(
            dataset_storage.read_bytes(
                "curated/worklogs/space=click-price/year=2026/month=03/worklogs.parquet"
            )
        )
    ).to_pylist()
    bigquery_rows = bigquery_client.table_rows("jira-report-489919.jirareport.worklogs")
    worksheet_rows = service.worksheet_rows("cp-2026", "03")

    assert raw_issue_types == ["Bug", "Story"]
    assert [row["issue_type"] for row in parquet_rows] == ["Bug", "Story"]
    assert [row["issue_type"] for row in bigquery_rows] == ["Bug", "Story"]
    assert worksheet_rows[0][8] == "issue_type"
    assert worksheet_rows[1][8] == "Bug"
    assert worksheet_rows[2][8] == "Story"
