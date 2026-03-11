from __future__ import annotations

from typing import Any, Protocol

from jirareport.domain.models import DateRange, WorklogEntry


class WorklogSource(Protocol):
    def fetch_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        """Fetches worklogs for the provided date window."""


class ReportStorage(Protocol):
    def write_json(self, path: str, payload: dict[str, Any]) -> str:
        """Writes JSON payload and returns the storage path."""

