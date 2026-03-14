from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import pyarrow.parquet as pq


@dataclass
class FakeBigQueryJob:
    """Represents one completed BigQuery job with a predefined response."""

    response: Any = None

    def result(self) -> Any:
        """Returns the predefined job response."""
        return self.response


@dataclass
class FakeTableState:
    """Stores rows and schema metadata for one fake BigQuery table."""

    schema_fields: list[str]
    rows: list[dict[str, object]] = field(default_factory=list)
    partition_field: str | None = None
    clustering_fields: list[str] = field(default_factory=list)


@dataclass
class FakeViewState:
    """Stores the query text for one fake BigQuery view."""

    table_id: str
    view_query: str


class StatefulFakeBigQueryClient:
    """In-memory BigQuery client that understands the adapter's SQL subset."""

    def __init__(self) -> None:
        self.tables: dict[str, FakeTableState] = {}
        self.views: dict[str, FakeViewState] = {}
        self.queries: list[str] = []
        self.loads: list[tuple[str, list[dict[str, object]]]] = []
        self.updated_views: list[str] = []

    def query(self, query: str, job_config: Any) -> FakeBigQueryJob:
        """Executes one supported SQL statement against in-memory state."""
        self.queries.append(query)
        if query.startswith("ALTER TABLE"):
            self._handle_alter_table(query)
            return FakeBigQueryJob([])
        if query.startswith("DELETE FROM"):
            self._handle_delete(query, job_config)
            return FakeBigQueryJob([])
        if "GROUP BY worklog_id" in query:
            return FakeBigQueryJob(self._handle_duplicate_check(query, job_config))
        raise AssertionError(f"Unsupported fake BigQuery query: {query}")

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
    ) -> FakeBigQueryJob:
        """Appends rows decoded from a Parquet payload to one fake table."""
        del size, num_retries, job_id, job_id_prefix, location, project, job_config, timeout
        assert rewind is True
        table_ref = str(destination)
        payload = file_obj.read()
        rows = pq.read_table(BytesIO(payload)).to_pylist()
        self.tables[table_ref].rows.extend(rows)
        self.loads.append((table_ref, rows))
        return FakeBigQueryJob()

    def create_table(self, table: Any, exists_ok: bool) -> Any:
        """Creates a fake table or view if missing and returns its state holder."""
        assert exists_ok is True
        table_ref = _qualified_table_ref(table)
        if getattr(table, "view_query", None):
            view = self.views.get(table_ref)
            if view is None:
                view = FakeViewState(table_id=table.table_id, view_query=str(table.view_query))
                self.views[table_ref] = view
            return view
        if table_ref not in self.tables:
            self.tables[table_ref] = FakeTableState(
                schema_fields=[field.name for field in table.schema],
                partition_field=(table.time_partitioning.field if table.time_partitioning else None),
                clustering_fields=list(table.clustering_fields or []),
            )
        return table

    def update_table(self, table: Any, fields: list[str]) -> Any:
        """Updates an existing fake view definition."""
        assert fields == ["view_query"]
        table_ref = _qualified_table_ref(table)
        self.views[table_ref] = FakeViewState(
            table_id=table.table_id,
            view_query=str(table.view_query),
        )
        self.updated_views.append(table_ref)
        return self.views[table_ref]

    def table_rows(self, table_ref: str) -> list[dict[str, object]]:
        """Returns all rows stored for one fake table."""
        return list(self.tables[table_ref].rows)

    def view_query(self, view_ref: str) -> str:
        """Returns the SQL query stored for one fake view."""
        return self.views[view_ref].view_query

    def _handle_alter_table(self, query: str) -> None:
        table_ref = _extract_table_ref(query)
        table = self.tables.get(table_ref)
        if table is None:
            return
        if "issue_type" not in table.schema_fields:
            table.schema_fields.append("issue_type")

    def _handle_delete(self, query: str, job_config: Any) -> None:
        table_ref = _extract_table_ref(query)
        params = _query_parameters(job_config)
        space_slug = str(params["space_slug"])
        report_month = str(params["report_month"])
        table = self.tables[table_ref]
        table.rows = [
            row
            for row in table.rows
            if not (
                row.get("space_slug") == space_slug
                and row.get("report_month") == report_month
            )
        ]

    def _handle_duplicate_check(self, query: str, job_config: Any) -> list[dict[str, str]]:
        table_ref = _extract_table_ref(query)
        params = _query_parameters(job_config)
        space_slug = str(params["space_slug"])
        report_month = str(params["report_month"])
        table = self.tables[table_ref]
        worklog_ids = [
            str(row["worklog_id"])
            for row in table.rows
            if row.get("space_slug") == space_slug
            and row.get("report_month") == report_month
        ]
        duplicates = sorted(
            worklog_id
            for worklog_id, count in Counter(worklog_ids).items()
            if count > 1
        )
        return [{"worklog_id": worklog_id} for worklog_id in duplicates[:10]]


def _qualified_table_ref(table: Any) -> str:
    """Builds a canonical project.dataset.table reference for fake state storage."""
    return f"{table.project}.{table.dataset_id}.{table.table_id}"


def _extract_table_ref(query: str) -> str:
    """Extracts the backtick-enclosed table reference from one SQL statement."""
    match = re.search(r"`([^`]+)`", query)
    if match is None:
        raise AssertionError(f"Missing table reference in query: {query}")
    return match.group(1)


def _query_parameters(job_config: Any) -> dict[str, object]:
    """Returns query parameters keyed by their declared names."""
    parameters = getattr(job_config, "query_parameters", [])
    return {str(param.name): param.value for param in parameters}
