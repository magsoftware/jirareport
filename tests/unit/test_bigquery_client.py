from __future__ import annotations

from typing import Any

from jirareport.domain.models import JiraSpace, MonthId
from jirareport.infrastructure.google.bigquery_client import (
    BigQueryWarehouse,
    _reporting_views,
)


class FakeJob:
    def result(self) -> None:
        return None


class FakeBigQueryClient:
    def __init__(self) -> None:
        self.queries: list[tuple[str, Any]] = []
        self.loads: list[tuple[bytes, str, Any]] = []
        self.tables: dict[str, Any] = {}
        self.updated: list[str] = []

    def query(self, query: str, job_config: Any) -> FakeJob:
        self.queries.append((query, job_config))
        return FakeJob()

    def load_table_from_file(
        self,
        file_obj: Any,
        destination: str,
        job_config: Any,
        rewind: bool,
    ) -> FakeJob:
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


def test_bigquery_warehouse_loads_month_slice_from_parquet() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWarehouse(
        project_id="jira-report-489919",
        dataset="jirareport",
        table="worklogs",
        client_factory=lambda: client,
    )

    warehouse.load_monthly_worklogs(
        JiraSpace(key="PRJ", name="Project", slug="project"),
        MonthId(year=2026, month=3),
        b"PAR1",
    )

    assert len(client.queries) == 1
    assert (
        "DELETE FROM `jira-report-489919.jirareport.worklogs`"
        in client.queries[0][0]
    )
    assert client.loads[0][0] == b"PAR1"
    assert client.loads[0][1] == "jira-report-489919.jirareport.worklogs"


def test_bigquery_warehouse_ensures_reporting_views() -> None:
    client = FakeBigQueryClient()
    warehouse = BigQueryWarehouse(
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


def test_reporting_views_reference_source_table() -> None:
    views = _reporting_views("jira-report-489919.jirareport.worklogs")

    assert "by_issue" in views
    assert "FROM `jira-report-489919.jirareport.worklogs`" in views["by_issue"]
