from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from jirareport.domain.models import MonthId, WorklogEntry


def format_datetime(value: datetime) -> str:
    """Formats a datetime without fractional seconds for report output.

    Args:
        value: Datetime value emitted into report payloads.

    Returns:
        ISO 8601 datetime string truncated to whole seconds.
    """
    return value.isoformat(timespec="seconds")


def filter_worklogs_for_month(
    worklogs: Iterable[WorklogEntry],
    month: MonthId,
) -> list[WorklogEntry]:
    """Returns only worklogs whose local start date belongs to the month.

    Args:
        worklogs: Worklog entries to filter.
        month: Target calendar month used as the inclusion criterion.

    Returns:
        Filtered list of worklogs starting within the requested month.
    """
    return [entry for entry in worklogs if month.contains(entry.started_date)]
