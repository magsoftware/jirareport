from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from io import BytesIO
from typing import IO, Any, Protocol, cast

import pyarrow.parquet as pq
from google.cloud import bigquery

from jirareport.domain.models import JiraSpace, MonthId


class BigQueryJob(Protocol):
    """Describes the subset of BigQuery job behavior used by the adapter."""

    def result(self) -> object:
        """Waits for the job to complete and returns the job result."""


class BigQueryClientProtocol(Protocol):
    """Describes the subset of BigQuery client behavior used by the adapter."""

    def query(
        self,
        query: str,
        job_config: bigquery.QueryJobConfig,
    ) -> BigQueryJob:
        """Executes a SQL query."""

    def load_table_from_file(
        self,
        file_obj: IO[bytes],
        destination: Any,
        rewind: bool = False,
        size: int | None = None,
        num_retries: int = 6,
        job_id: str | None = None,
        job_id_prefix: str | None = None,
        location: str | None = None,
        project: str | None = None,
        job_config: bigquery.LoadJobConfig | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> BigQueryJob:
        """Loads tabular data from a file-like object."""

    def create_table(
        self,
        table: bigquery.Table,
        exists_ok: bool,
    ) -> bigquery.Table:
        """Creates a table or returns the existing one."""

    def update_table(
        self,
        table: bigquery.Table,
        fields: list[str],
    ) -> bigquery.Table:
        """Updates selected table fields."""


BigQueryClientFactory = Callable[[], BigQueryClientProtocol]
WORKLOGS_SCHEMA = (
    bigquery.SchemaField("space_key", "STRING"),
    bigquery.SchemaField("space_name", "STRING"),
    bigquery.SchemaField("space_slug", "STRING"),
    bigquery.SchemaField("report_month", "STRING"),
    bigquery.SchemaField("worklog_id", "STRING"),
    bigquery.SchemaField("issue_key", "STRING"),
    bigquery.SchemaField("issue_summary", "STRING"),
    bigquery.SchemaField("author_name", "STRING"),
    bigquery.SchemaField("author_account_id", "STRING"),
    bigquery.SchemaField("started_at", "STRING"),
    bigquery.SchemaField("ended_at", "STRING"),
    bigquery.SchemaField("started_date", "DATE"),
    bigquery.SchemaField("ended_date", "DATE"),
    bigquery.SchemaField("crosses_midnight", "BOOL"),
    bigquery.SchemaField("duration_seconds", "INT64"),
    bigquery.SchemaField("duration_hours", "FLOAT64"),
)


class BigQueryWorklogWarehouse:
    """Loads curated worklogs into BigQuery and maintains reporting views."""

    def __init__(
        self,
        project_id: str,
        dataset: str,
        spaces: tuple[JiraSpace, ...],
        table: str = "worklogs",
        client_factory: BigQueryClientFactory | None = None,
    ) -> None:
        """Initializes the reporting warehouse client and target metadata."""
        self._project_id = project_id
        self._dataset = dataset
        self._spaces = spaces
        self._table = table
        self._client_factory = client_factory or self._default_client_factory

    def load_monthly_worklogs(
        self,
        space: JiraSpace,
        month: MonthId,
        parquet_payload: bytes,
    ) -> None:
        """Replaces one space/month slice in the worklogs table using Parquet."""
        duplicate_ids = _duplicate_worklog_ids_in_parquet(parquet_payload)
        if duplicate_ids:
            formatted_ids = ", ".join(duplicate_ids)
            raise ValueError(
                "Duplicate worklog_id values detected in curated payload for "
                f"space={space.slug} month={month.label()}: {formatted_ids}"
            )
        client = self._client_factory()
        _ensure_worklogs_table(client, self._table_ref)
        _delete_month_slice(client, self._table_ref, space.slug, month.label())
        _load_month_slice(client, self._table_ref, parquet_payload)
        duplicate_ids = _duplicate_worklog_ids(
            client,
            self._table_ref,
            space.slug,
            month.label(),
        )
        if duplicate_ids:
            _delete_month_slice(client, self._table_ref, space.slug, month.label())
            formatted_ids = ", ".join(duplicate_ids)
            raise ValueError(
                "Duplicate worklog_id values detected for "
                f"space={space.slug} month={month.label()}: {formatted_ids}"
            )

    def ensure_views(self) -> None:
        """Creates or refreshes the reporting views built on top of worklogs."""
        client = self._client_factory()
        for view_name, query in _reporting_view_queries(
            self._table_ref,
            self._spaces,
        ).items():
            _ensure_view(client, self._dataset_ref, view_name, query)

    @property
    def _dataset_ref(self) -> str:
        return f"{self._project_id}.{self._dataset}"

    @property
    def _table_ref(self) -> str:
        return f"{self._dataset_ref}.{self._table}"

    def _default_client_factory(self) -> BigQueryClientProtocol:
        return cast(
            BigQueryClientProtocol,
            bigquery.Client(project=self._project_id),
        )


def _delete_month_slice(
    client: BigQueryClientProtocol,
    table_ref: str,
    space_slug: str,
    report_month: str,
) -> None:
    """Deletes the current month slice before reloading curated worklogs."""
    query = (
        f"DELETE FROM `{table_ref}` "
        "WHERE space_slug = @space_slug AND report_month = @report_month"
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("space_slug", "STRING", space_slug),
            bigquery.ScalarQueryParameter("report_month", "STRING", report_month),
        ]
    )
    client.query(query, job_config=config).result()


def _ensure_worklogs_table(
    client: BigQueryClientProtocol,
    table_ref: str,
) -> None:
    """Creates the worklogs table when the target dataset is still empty."""
    table = bigquery.Table(table_ref, schema=list(WORKLOGS_SCHEMA))
    table.time_partitioning = bigquery.TimePartitioning(field="started_date")
    table.clustering_fields = ["space_slug", "author_name", "issue_key"]
    client.create_table(table, exists_ok=True)


def _load_month_slice(
    client: BigQueryClientProtocol,
    table_ref: str,
    parquet_payload: bytes,
) -> None:
    """Appends one curated month slice from a Parquet payload."""
    load_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        time_partitioning=bigquery.TimePartitioning(field="started_date"),
        clustering_fields=["space_slug", "author_name", "issue_key"],
    )
    client.load_table_from_file(
        BytesIO(parquet_payload),
        table_ref,
        job_config=load_config,
        rewind=True,
    ).result()


def _ensure_view(
    client: BigQueryClientProtocol,
    dataset_ref: str,
    view_name: str,
    query: str,
) -> None:
    """Creates or refreshes one reporting view."""
    view = bigquery.Table(f"{dataset_ref}.{view_name}")
    view.view_query = query
    view = client.create_table(view, exists_ok=True)
    if view.view_query != query:
        view.view_query = query
        client.update_table(view, ["view_query"])


def _duplicate_worklog_ids(
    client: BigQueryClientProtocol,
    table_ref: str,
    space_slug: str,
    report_month: str,
) -> list[str]:
    """Returns duplicate worklog IDs detected for one loaded month slice."""
    query = (
        "SELECT worklog_id "
        f"FROM `{table_ref}` "
        "WHERE space_slug = @space_slug AND report_month = @report_month "
        "GROUP BY worklog_id "
        "HAVING COUNT(*) > 1 "
        "ORDER BY worklog_id "
        "LIMIT 10"
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("space_slug", "STRING", space_slug),
            bigquery.ScalarQueryParameter("report_month", "STRING", report_month),
        ]
    )
    result = client.query(query, job_config=config).result()
    return [str(row["worklog_id"]) for row in cast(Iterable[Any], result)]


def _duplicate_worklog_ids_in_parquet(parquet_payload: bytes) -> list[str]:
    """Returns duplicate worklog IDs detected directly in a Parquet payload."""
    table = pq.read_table(BytesIO(parquet_payload), columns=["worklog_id"])
    values = [
        str(value)
        for value in table.column("worklog_id").to_pylist()
        if value not in {None, ""}
    ]
    counts = Counter(values)
    duplicates = sorted(
        worklog_id
        for worklog_id, count in counts.items()
        if count > 1
    )
    return duplicates[:10]


def _reporting_view_queries(
    table_ref: str,
    spaces: tuple[JiraSpace, ...],
) -> dict[str, str]:
    """Builds all analytical view queries for global and per-space reporting."""
    queries = {
        "all_spaces_worklogs": _worklogs_query(table_ref),
        "all_spaces_by_issue": _by_issue_query(table_ref),
        "all_spaces_by_issue_author": _by_issue_author_query(table_ref),
        "all_spaces_by_author": _by_author_query(table_ref),
        "all_spaces_author_daily": _author_daily_query(table_ref),
        "all_spaces_team_daily": _team_daily_query(table_ref),
    }
    for space in spaces:
        prefix = _space_view_prefix(space.slug)
        queries[f"{prefix}_worklogs"] = _worklogs_query(table_ref, space.slug)
        queries[f"{prefix}_by_issue"] = _by_issue_query(table_ref, space.slug)
        queries[f"{prefix}_by_issue_author"] = _by_issue_author_query(
            table_ref,
            space.slug,
        )
        queries[f"{prefix}_by_author"] = _by_author_query(table_ref, space.slug)
        queries[f"{prefix}_author_daily"] = _author_daily_query(table_ref, space.slug)
        queries[f"{prefix}_team_daily"] = _team_daily_query(table_ref, space.slug)
    return queries


def _worklogs_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the raw worklogs view query."""
    return (
        "SELECT * "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
    ).strip()


def _by_issue_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the hours-by-issue aggregation query."""
    return (
        "SELECT "
        "space_key, "
        "space_name, "
        "report_month, "
        "space_slug, "
        "issue_key, "
        "issue_summary, "
        "ROUND(SUM(duration_hours), 2) AS total_hours "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
        "GROUP BY "
        "space_key, space_name, report_month, space_slug, "
        "issue_key, issue_summary"
    ).strip()


def _by_issue_author_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the hours-by-issue-and-author aggregation query."""
    return (
        "SELECT "
        "space_key, "
        "space_name, "
        "report_month, "
        "space_slug, "
        "issue_key, "
        "issue_summary, "
        "author_name, "
        "author_account_id, "
        "ROUND(SUM(duration_hours), 2) AS total_hours "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
        "GROUP BY "
        "space_key, space_name, report_month, space_slug, "
        "issue_key, issue_summary, author_name, author_account_id"
    ).strip()


def _by_author_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the hours-by-author aggregation query."""
    return (
        "SELECT "
        "space_key, "
        "space_name, "
        "report_month, "
        "space_slug, "
        "author_name, "
        "author_account_id, "
        "ROUND(SUM(duration_hours), 2) AS total_hours "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
        "GROUP BY "
        "space_key, space_name, report_month, space_slug, "
        "author_name, author_account_id"
    ).strip()


def _author_daily_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the per-author daily aggregation query."""
    return (
        "SELECT "
        "started_date AS date, "
        "space_key, "
        "space_name, "
        "report_month, "
        "space_slug, "
        "author_name, "
        "author_account_id, "
        "ROUND(SUM(duration_hours), 2) AS total_hours "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
        "GROUP BY "
        "date, space_key, space_name, report_month, space_slug, "
        "author_name, author_account_id"
    ).strip()


def _team_daily_query(table_ref: str, space_slug: str | None = None) -> str:
    """Builds the per-day team aggregation query."""
    return (
        "SELECT "
        "started_date AS date, "
        "space_key, "
        "space_name, "
        "report_month, "
        "space_slug, "
        "author_name, "
        "author_account_id, "
        "ROUND(SUM(duration_hours), 2) AS total_hours "
        f"FROM `{table_ref}` "
        f"{_space_filter_clause(space_slug)}"
        "GROUP BY "
        "date, space_key, space_name, report_month, space_slug, "
        "author_name, author_account_id"
    ).strip()


def _space_filter_clause(space_slug: str | None) -> str:
    """Returns an optional SQL filter clause for one reporting space."""
    if space_slug is None:
        return ""
    return f"WHERE space_slug = '{space_slug}' "


def _space_view_prefix(space_slug: str) -> str:
    """Normalizes a space slug into a BigQuery-safe view name prefix."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", space_slug).strip("_").lower()
    return normalized
