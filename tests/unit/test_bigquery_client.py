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
        table="worklogs",
        client_factory=lambda: client,
    )
    payload = _parquet_payload(["wl-1"])

    warehouse.load_monthly_worklogs(
        JiraSpace(key="PRJ", name="Project", slug="project"),
        MonthId(year=2026, month=3),
        payload,
    )

    assert len(client.queries) == 2
    assert (
        "DELETE FROM `jira-report-489919.jirareport.worklogs`"
        in client.queries[0][0]
    )
    assert "GROUP BY worklog_id" in client.queries[1][0]
    assert client.loads[0][0] == payload
    assert client.loads[0][1] == "jira-report-489919.jirareport.worklogs"


def test_bigquery_warehouse_rejects_duplicate_worklog_ids_in_curated_payload() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
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
    client.query_results = [[], [{"worklog_id": "duplicate-1"}], []]
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
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

    assert len(client.queries) == 3
    assert "GROUP BY worklog_id" in client.queries[1][0]
    assert (
        "DELETE FROM `jira-report-489919.jirareport.worklogs`"
        in client.queries[2][0]
    )


def test_bigquery_warehouse_ensures_reporting_views() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWorklogWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        table="worklogs",
        client_factory=lambda: client,
    )

    warehouse.ensure_views()

    assert set(client.tables) == {
        "by_issue",
        "by_issue_author",
        "by_author",
        "author_daily",
        "team_daily",
    }


def test_bigquery_warehouse_updates_existing_view_when_query_changes() -> None:
    existing_view = type(
        "View",
        (),
        {"table_id": "by_issue", "view_query": "SELECT 1"},
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
        table="worklogs",
        client_factory=lambda: client,
    )

    warehouse.ensure_views()

    assert "by_issue" in client.updated


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
    )

    client = warehouse._default_client_factory()

    assert created_projects == ["jira-report-489919"]
    assert isinstance(client, FakeClient)


def test_reporting_views_reference_source_table() -> None:
    views = _reporting_view_queries("jira-report-489919.jirareport.worklogs")

    assert "by_issue" in views
    assert "FROM `jira-report-489919.jirareport.worklogs`" in views["by_issue"]
