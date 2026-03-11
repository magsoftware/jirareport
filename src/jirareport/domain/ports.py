from __future__ import annotations

from typing import Any, Protocol

from jirareport.domain.models import (
    DateRange,
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


class SpreadsheetPublisher(Protocol):
    """Publishes tabular report data to a spreadsheet backend."""

    def publish(self, request: SpreadsheetPublishRequest) -> str:
        """Publishes a yearly spreadsheet payload and returns its URL."""


class SpreadsheetResolver(Protocol):
    """Resolves or creates the yearly spreadsheet used for publishing."""

    def resolve(self, year: int) -> SpreadsheetTarget:
        """Returns the spreadsheet target for the requested year."""
