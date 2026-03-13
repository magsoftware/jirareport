from __future__ import annotations

from typing import Any, Protocol

from jirareport.domain.models import (
    DateRange,
    JiraSpace,
    MonthId,
    SpreadsheetPublishRequest,
    SpreadsheetTarget,
    WorklogEntry,
)


class WorklogSource(Protocol):
    """Provides normalized worklog entries for a requested date window."""

    def fetch_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        """Fetches worklogs for the provided date window."""


class ReportStorage(Protocol):
    """Persists serialized report payloads to a target storage backend."""

    def write_json(self, path: str, payload: dict[str, Any]) -> str:
        """Writes JSON payload and returns the storage path."""

    def write_parquet(self, path: str, payload: bytes) -> str:
        """Writes Parquet payload and returns the storage path."""

    def read_bytes(self, path: str) -> bytes:
        """Reads a previously stored binary payload."""


class SpreadsheetPublisher(Protocol):
    """Publishes tabular report data to a spreadsheet backend."""

    def publish(self, request: SpreadsheetPublishRequest) -> str:
        """Publishes a yearly spreadsheet payload and returns its URL."""


class SpreadsheetResolver(Protocol):
    """Resolves or creates the yearly spreadsheet used for publishing."""

    def resolve(self, year: int) -> SpreadsheetTarget:
        """Returns the spreadsheet target for the requested year."""


class ReportingWarehouse(Protocol):
    """Publishes curated monthly worklogs into the analytical warehouse."""

    def load_monthly_worklogs(
        self,
        space: JiraSpace,
        month: MonthId,
        parquet_payload: bytes,
    ) -> None:
        """Loads one month's curated worklogs into the warehouse."""

    def ensure_views(self) -> None:
        """Ensures analytical reporting views exist and are up to date."""
