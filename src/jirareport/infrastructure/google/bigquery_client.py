from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from typing import Any

from google.cloud import bigquery

from jirareport.domain.models import JiraSpace, MonthId

BigQueryClientFactory = Callable[[], Any]


class BigQueryWarehouse:
    """Loads curated worklogs into BigQuery and maintains reporting views."""

    def __init__(
        self,
        project_id: str,
        dataset: str,
        table: str = "worklogs",
        client_factory: BigQueryClientFactory | None = None,
    ) -> None:
        """Initializes the warehouse client and target dataset metadata."""
        self._project_id = project_id
        self._dataset = dataset
        self._table = table
        self._client_factory = client_factory or self._default_client_factory

    def load_monthly_worklogs(
        self,
        space: JiraSpace,
        month: MonthId,
        parquet_payload: bytes,
    ) -> None:
        """Replaces one space/month slice in the worklogs table using Parquet."""
        client = self._client_factory()
        self._delete_month_slice(client, space.slug, month.label())
        load_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
            time_partitioning=bigquery.TimePartitioning(field="started_date"),
            clustering_fields=["space_slug", "author_name", "issue_key"],
        )
        job = client.load_table_from_file(
            BytesIO(parquet_payload),
            self._table_ref,
            job_config=load_config,
            rewind=True,
        )
        job.result()

    def ensure_views(self) -> None:
        """Creates or refreshes the reporting views built on top of worklogs."""
        client = self._client_factory()
        for view_name, query in _reporting_views(self._table_ref).items():
            view = bigquery.Table(f"{self._dataset_ref}.{view_name}")
            view.view_query = query
            view = client.create_table(view, exists_ok=True)
            if view.view_query != query:
                view.view_query = query
                client.update_table(view, ["view_query"])

    @property
    def _dataset_ref(self) -> str:
        return f"{self._project_id}.{self._dataset}"

    @property
    def _table_ref(self) -> str:
        return f"{self._dataset_ref}.{self._table}"

    def _delete_month_slice(
        self,
        client: Any,
        space_slug: str,
        report_month: str,
    ) -> None:
        query = (
            f"DELETE FROM `{self._table_ref}` "
            "WHERE space_slug = @space_slug AND report_month = @report_month"
        )
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("space_slug", "STRING", space_slug),
                bigquery.ScalarQueryParameter("report_month", "STRING", report_month),
            ]
        )
        client.query(query, job_config=config).result()

    def _default_client_factory(self) -> Any:
        return bigquery.Client(project=self._project_id)


def _reporting_views(table_ref: str) -> dict[str, str]:
    """Returns SQL definitions for the BigQuery reporting views."""
    return {
        "by_issue": (
            "SELECT "
            "space_key, space_name, space_slug, report_month, "
            "issue_key, issue_summary, "
            "ROUND(SUM(duration_hours), 2) AS total_hours "
            f"FROM `{table_ref}` "
            "GROUP BY space_key, space_name, space_slug, report_month, "
            "issue_key, issue_summary"
        ),
        "by_issue_author": (
            "SELECT "
            "space_key, space_name, space_slug, report_month, "
            "issue_key, issue_summary, author_name, author_account_id, "
            "ROUND(SUM(duration_hours), 2) AS total_hours "
            f"FROM `{table_ref}` "
            "GROUP BY "
            "space_key, space_name, space_slug, report_month, "
            "issue_key, issue_summary, "
            "author_name, author_account_id"
        ),
        "by_author": (
            "SELECT "
            "space_key, space_name, space_slug, report_month, "
            "author_name, author_account_id, "
            "ROUND(SUM(duration_hours), 2) AS total_hours "
            f"FROM `{table_ref}` "
            "GROUP BY "
            "space_key, space_name, space_slug, report_month, "
            "author_name, author_account_id"
        ),
        "author_daily": (
            "SELECT "
            "space_key, space_name, space_slug, report_month, "
            "started_date AS date, author_name, author_account_id, "
            "ROUND(SUM(duration_hours), 2) AS total_hours "
            f"FROM `{table_ref}` "
            "GROUP BY "
            "space_key, space_name, space_slug, report_month, "
            "date, author_name, author_account_id"
        ),
        "team_daily": (
            "SELECT "
            "space_key, space_name, space_slug, report_month, "
            "started_date AS date, author_name, author_account_id, "
            "ROUND(SUM(duration_hours), 2) AS total_hours "
            f"FROM `{table_ref}` "
            "GROUP BY "
            "space_key, space_name, space_slug, report_month, "
            "date, author_name, author_account_id"
        ),
    }
