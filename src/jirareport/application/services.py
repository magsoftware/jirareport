from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from jirareport.application.serializers import (
    serialize_daily_snapshot,
    serialize_monthly_report,
)
from jirareport.domain.models import (
    DailyRawSnapshot,
    DateRange,
    MonthId,
    MonthlyWorklogReport,
    TicketWorklogReport,
    WorklogEntry,
)
from jirareport.domain.ports import ReportStorage, WorklogSource
from jirareport.domain.time_range import month_range, months_in_range, rolling_window


@dataclass(frozen=True)
class DailySnapshotResult:
    snapshot_path: str
    monthly_paths: tuple[str, ...]
    worklog_count: int


@dataclass(frozen=True)
class MonthlyReportResult:
    report_path: str
    ticket_count: int
    worklog_count: int


class DailySnapshotService:
    def __init__(
        self,
        source: WorklogSource,
        storage: ReportStorage,
        project_key: str,
        timezone_name: str,
    ) -> None:
        self._source = source
        self._storage = storage
        self._project_key = project_key
        self._timezone = ZoneInfo(timezone_name)
        self._timezone_name = timezone_name

    def generate(self, reference_date: date) -> DailySnapshotResult:
        window = rolling_window(reference_date)
        generated_at = datetime.now(self._timezone)
        worklogs = _sort_worklogs(self._source.fetch_worklogs(window))
        snapshot = DailyRawSnapshot(
            project_key=self._project_key,
            snapshot_date=reference_date,
            window=window,
            generated_at=generated_at,
            timezone_name=self._timezone_name,
            worklogs=tuple(worklogs),
        )
        snapshot_path = self._storage.write_json(
            _daily_snapshot_path(reference_date),
            serialize_daily_snapshot(snapshot),
        )
        monthly_paths = self._write_monthly_reports(worklogs, window, generated_at)
        logger.info("Generated snapshot with {} worklogs.", len(worklogs))
        return DailySnapshotResult(snapshot_path, monthly_paths, len(worklogs))

    def _write_monthly_reports(
        self,
        worklogs: list[WorklogEntry],
        window: DateRange,
        generated_at: datetime,
    ) -> tuple[str, ...]:
        paths: list[str] = []
        for month in months_in_range(window):
            report = _build_monthly_report(
                worklogs,
                self._project_key,
                month,
                generated_at,
                self._timezone_name,
            )
            path = self._storage.write_json(
                _monthly_report_path(month),
                serialize_monthly_report(report),
            )
            paths.append(path)
        return tuple(paths)


class MonthlyReportService:
    def __init__(
        self,
        source: WorklogSource,
        storage: ReportStorage,
        project_key: str,
        timezone_name: str,
    ) -> None:
        self._source = source
        self._storage = storage
        self._project_key = project_key
        self._timezone = ZoneInfo(timezone_name)
        self._timezone_name = timezone_name

    def generate(self, month: MonthId) -> MonthlyReportResult:
        window = month_range(month)
        generated_at = datetime.now(self._timezone)
        worklogs = _sort_worklogs(self._source.fetch_worklogs(window))
        report = _build_monthly_report(
            worklogs,
            self._project_key,
            month,
            generated_at,
            self._timezone_name,
        )
        report_path = self._storage.write_json(
            _monthly_report_path(month),
            serialize_monthly_report(report),
        )
        ticket_count = len(report.tickets)
        return MonthlyReportResult(report_path, ticket_count, len(worklogs))


def _build_monthly_report(
    worklogs: list[WorklogEntry],
    project_key: str,
    month: MonthId,
    generated_at: datetime,
    timezone_name: str,
) -> MonthlyWorklogReport:
    relevant = [entry for entry in worklogs if month.contains(entry.started_at.date())]
    tickets: dict[tuple[str, str], list[WorklogEntry]] = {}
    for entry in relevant:
        key = (entry.issue_key, entry.issue_summary)
        tickets.setdefault(key, []).append(entry)
    ticket_reports = tuple(
        TicketWorklogReport(
            issue_key=issue_key,
            summary=summary,
            bookings=tuple(_sort_worklogs(entries)),
        )
        for issue_key, summary, entries in _sorted_tickets(tickets)
    )
    return MonthlyWorklogReport(
        project_key=project_key,
        month=month,
        generated_at=generated_at,
        timezone_name=timezone_name,
        tickets=ticket_reports,
    )


def _sorted_tickets(
    tickets: dict[tuple[str, str], list[WorklogEntry]]
) -> list[tuple[str, str, list[WorklogEntry]]]:
    items = [
        (issue_key, summary, entries)
        for (issue_key, summary), entries in tickets.items()
    ]
    return sorted(items, key=lambda item: item[0])


def _sort_worklogs(worklogs: list[WorklogEntry]) -> list[WorklogEntry]:
    return sorted(
        worklogs,
        key=lambda item: (item.issue_key, item.started_at, item.worklog_id),
    )


def _daily_snapshot_path(reference_date: date) -> str:
    return f"raw/daily/{reference_date:%Y/%m/%Y-%m-%d}.json"


def _monthly_report_path(month: MonthId) -> str:
    return f"derived/monthly/{month.year:04d}/{month.label()}.json"
