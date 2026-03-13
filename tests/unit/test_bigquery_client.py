from __future__ import annotations

from io import BytesIO
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from jirareport.domain.models import JiraSpace, MonthId
from jirareport.infrastructure.google.bigquery_client import (
    BigQueryWorklogWarehouse,
    _reporting_view_queries,
)


class FakeJob:
    def __init__(self, response: Any = None) -> None:
        self._response = response

    def result(self) -> Any:
        return self._response


class FakeBigQueryClient:
    def __init__(self) -> None:
        self.queries: list[tuple[str, Any]] = []
        self.loads: list[tuple[bytes, str, Any]] = []
        self.tables: dict[str, Any] = {}
        self.updated: list[str] = []
        self.query_results: list[Any] = []

    def query(self, query: str, job_config: Any) -> FakeJob:
        self.queries.append((query, job_config))
        response = self.query_results.pop(0) if self.query_results else []
        return FakeJob(response)

    def load_table_from_file(
        self,
        file_obj: Any,
        destination: Any,
        rewind: bool = False,
        size: int | None = None,
        num_retries: int = 6,
        job_id: str | None = None,
        job_id_prefix: str | None = None,
        location: str | None = None,
        project: str | None = None,
        job_config: Any = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> FakeJob:
        del size, num_retries, job_id, job_id_prefix, location, project, timeout
        assert rewind is True
        self.loads.append((file_obj.read(), destination, job_config))
        return FakeJob()

    def create_table(self, table: Any, exists_ok: bool) -> Any:
        assert exists_ok is True
        self.tables[table.table_id] = table
        return table

    def update_table(self, table: Any, fields: list[str]) -> Any:
        self.updated.append(table.table_id)
        return table


def _parquet_payload(worklog_ids: list[str]) -> bytes:
    table = pa.table({"worklog_id": worklog_ids})
    buffer = BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


def test_bigquery_warehouse_loads_month_slice_from_parquet() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(JiraSpace(key="PRJ", name="Project", slug="project"),),
        table="worklogs",
        client_factory=lambda: client,
    )
    payload = _parquet_payload(["wl-1"])

    warehouse.load_monthly_worklogs(
        JiraSpace(key="PRJ", name="Project", slug="project"),
        MonthId(year=2026, month=3),
        payload,
    )

    assert len(client.queries) == 3
    assert "worklogs" in client.tables
    assert "ADD COLUMN IF NOT EXISTS issue_type" in client.queries[0][0]
    assert (
        "DELETE FROM `jira-report-489919.jirareport.worklogs`"
        in client.queries[1][0]
    )
    assert "GROUP BY worklog_id" in client.queries[2][0]
    assert client.loads[0][0] == payload
    assert client.loads[0][1] == "jira-report-489919.jirareport.worklogs"


def test_bigquery_warehouse_rejects_duplicate_worklog_ids_in_curated_payload() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(JiraSpace(key="PRJ", name="Project", slug="project"),),
        table="worklogs",
        client_factory=lambda: client,
    )
    payload = _parquet_payload(["duplicate-1", "duplicate-1"])

    with pytest.raises(
        ValueError,
        match="Duplicate worklog_id values detected in curated payload",
    ):
        warehouse.load_monthly_worklogs(
            JiraSpace(key="PRJ", name="Project", slug="project"),
            MonthId(year=2026, month=3),
            payload,
        )

    assert client.queries == []
    assert client.loads == []


def test_bigquery_warehouse_rejects_duplicate_worklog_ids_after_load() -> None:
    client = FakeBigQueryClient()
    client.query_results = [[], [], [{"worklog_id": "duplicate-1"}], []]
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(JiraSpace(key="PRJ", name="Project", slug="project"),),
        table="worklogs",
        client_factory=lambda: client,
    )
    payload = _parquet_payload(["wl-1"])

    with pytest.raises(ValueError, match="Duplicate worklog_id values detected for"):
        warehouse.load_monthly_worklogs(
            JiraSpace(key="PRJ", name="Project", slug="project"),
            MonthId(year=2026, month=3),
            payload,
        )

    assert len(client.queries) == 4
    assert "GROUP BY worklog_id" in client.queries[2][0]
    assert (
        "DELETE FROM `jira-report-489919.jirareport.worklogs`"
        in client.queries[3][0]
    )


def test_bigquery_warehouse_ensures_reporting_views() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(
            JiraSpace(key="LA004832", name="Click Price", slug="click-price"),
            JiraSpace(key="LA009644", name="Data Fixer", slug="data-fixer"),
        ),
        table="worklogs",
        client_factory=lambda: client,
    )

    warehouse.ensure_views()

    assert set(client.tables) == {
        "all_spaces_worklogs",
        "all_spaces_by_issue",
        "all_spaces_by_issue_author",
        "all_spaces_by_author",
        "all_spaces_author_daily",
        "all_spaces_team_daily",
        "click_price_worklogs",
        "click_price_by_issue",
        "click_price_by_issue_author",
        "click_price_by_author",
        "click_price_author_daily",
        "click_price_team_daily",
        "data_fixer_worklogs",
        "data_fixer_by_issue",
        "data_fixer_by_issue_author",
        "data_fixer_by_author",
        "data_fixer_author_daily",
        "data_fixer_team_daily",
    }


def test_bigquery_warehouse_updates_existing_view_when_query_changes() -> None:
    existing_view = type(
        "View",
        (),
        {"table_id": "project_by_issue", "view_query": "SELECT 1"},
    )()

    class ExistingViewBigQueryClient(FakeBigQueryClient):
        def create_table(self, table: Any, exists_ok: bool) -> Any:
            assert exists_ok is True
            self.tables[table.table_id] = existing_view
            return existing_view

    client = ExistingViewBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(JiraSpace(key="PRJ", name="Project", slug="project"),),
        table="worklogs",
        client_factory=lambda: client,
    )

    warehouse.ensure_views()

    assert "project_by_issue" in client.updated


def test_bigquery_warehouse_uses_google_client_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_projects: list[str] = []

    class FakeClient:
        def __init__(self, project: str) -> None:
            created_projects.append(project)

    monkeypatch.setattr(
        "jirareport.infrastructure.google.bigquery_client.bigquery.Client",
        FakeClient,
    )
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        spaces=(),
    )

    client = warehouse._default_client_factory()

    assert created_projects == ["jira-report-489919"]
    assert isinstance(client, FakeClient)


def test_reporting_views_reference_source_table() -> None:
    views = _reporting_view_queries(
        "jira-report-489919.jirareport.worklogs",
        (
            JiraSpace(key="LA004832", name="Click Price", slug="click-price"),
            JiraSpace(key="LA009644", name="Data Fixer", slug="data-fixer"),
        ),
    )

    assert "all_spaces_by_issue" in views
    assert "click_price_by_issue" in views
    assert "data_fixer_by_issue" in views
    assert (
        "FROM `jira-report-489919.jirareport.worklogs`"
        in views["all_spaces_by_issue"]
    )
    assert "issue_type" in views["all_spaces_by_issue"]
    assert "WHERE space_slug = 'click-price'" in views["click_price_by_issue"]
    assert "WHERE space_slug = 'data-fixer'" in views["data_fixer_by_issue"]


def test_team_daily_view_aggregates_team_without_author_columns() -> None:
    views = _reporting_view_queries(
        "jira-report-489919.jirareport.worklogs",
        (JiraSpace(key="LA004832", name="Click Price", slug="click-price"),),
    )

    assert "author_name" in views["click_price_author_daily"]
    assert "author_account_id" in views["click_price_author_daily"]
    assert "author_name" not in views["click_price_team_daily"]
    assert "author_account_id" not in views["click_price_team_daily"]
    assert (
        "GROUP BY date, space_key, space_name, report_month, space_slug"
        in views["click_price_team_daily"]
    )
