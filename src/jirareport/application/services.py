from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from loguru import logger

from jirareport.application.parquet_serializers import (
    count_parquet_rows,
    serialize_monthly_worklogs,
)
from jirareport.application.serializers import (
    serialize_daily_snapshot,
    serialize_monthly_report,
)
from jirareport.application.spreadsheets import (
    build_spreadsheet_request,
    years_for_snapshot,
)
from jirareport.domain.models import (
    DailyRawSnapshot,
    DateRange,
    JiraSpace,
    MonthId,
    MonthlyWorklogReport,
    TicketWorklogReport,
    WorklogEntry,
)
from jirareport.domain.ports import (
    CuratedDatasetStorage,
    JsonReportStorage,
    SpreadsheetPublisher,
    SpreadsheetResolver,
    WorklogSource,
    WorklogWarehouse,
)
from jirareport.domain.time_range import (
    active_months,
    month_range,
    months_in_range,
    rolling_window,
)


@dataclass(frozen=True)
class DailySnapshotResult:
    """Describes the output of the daily snapshot use case."""

    snapshot_path: str
    monthly_paths: tuple[str, ...]
    curated_paths: tuple[str, ...]
    worklog_count: int


@dataclass(frozen=True)
class MonthlyReportResult:
    """Describes the output of the monthly report use case."""

    report_path: str
    curated_path: str
    ticket_count: int
    worklog_count: int


@dataclass(frozen=True)
class BackfillResult:
    """Describes the output of the historical backfill use case."""

    monthly_paths: tuple[str, ...]
    curated_paths: tuple[str, ...]
    worklog_count: int
    month_count: int


@dataclass(frozen=True)
class SpreadsheetSyncResult:
    """Describes the output of the Google Sheets synchronization use case."""

    spreadsheet_urls: tuple[str, ...]
    worklog_count: int


@dataclass(frozen=True)
class BigQuerySyncResult:
    """Describes the output of the BigQuery synchronization use case."""

    months: tuple[MonthId, ...]
    worklog_count: int


class _BaseTimedSpaceService:
    """Provides shared space and timezone context for application services."""

    def __init__(self, space: JiraSpace, timezone_name: str) -> None:
        """Initializes common service context."""
        self._space = space
        self._timezone = ZoneInfo(timezone_name)
        self._timezone_name = timezone_name


class _BaseSourceService(_BaseTimedSpaceService):
    """Provides shared worklog source access for application services."""

    def __init__(
        self,
        source: WorklogSource,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes source-backed service context."""
        super().__init__(space=space, timezone_name=timezone_name)
        self._source = source

    def _fetch_sorted_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        """Fetches worklogs for a window and sorts them deterministically."""
        return _fetch_sorted_worklogs(self._source, window)

    def _build_snapshot(
        self,
        snapshot_date: date,
        window: DateRange,
    ) -> DailyRawSnapshot:
        """Builds an in-memory snapshot for the requested window."""
        return _build_snapshot_for_window(
            source=self._source,
            space=self._space,
            snapshot_date=snapshot_date,
            window=window,
            timezone=self._timezone,
            timezone_name=self._timezone_name,
        )


class _BaseMonthlyReportService(_BaseSourceService):
    """Provides shared monthly report persistence for application services."""

    def __init__(
        self,
        source: WorklogSource,
        report_storage: JsonReportStorage,
        dataset_storage: CuratedDatasetStorage,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes report persistence dependencies."""
        super().__init__(source=source, space=space, timezone_name=timezone_name)
        self._report_storage = report_storage
        self._dataset_storage = dataset_storage

    def _write_monthly_reports(
        self,
        months: tuple[MonthId, ...],
        worklogs: list[WorklogEntry],
        generated_at: datetime,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[MonthlyWorklogReport, ...]]:
        """Writes derived monthly reports and curated datasets."""
        return _write_monthly_reports(
            report_storage=self._report_storage,
            dataset_storage=self._dataset_storage,
            space=self._space,
            months=months,
            worklogs=worklogs,
            generated_at=generated_at,
            timezone_name=self._timezone_name,
        )


class DailySnapshotService(_BaseMonthlyReportService):
    """Implements the main daily reporting use case.

    This service is the core of the tool. It fetches worklogs for the rolling
    reporting window, writes the raw daily snapshot, and refreshes all derived
    monthly reports affected by that window.
    """

    def __init__(
        self,
        source: WorklogSource,
        report_storage: JsonReportStorage,
        dataset_storage: CuratedDatasetStorage,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes the service with its reporting dependencies."""
        super().__init__(
            source=source,
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            timezone_name=timezone_name,
        )

    def generate(self, reference_date: date) -> DailySnapshotResult:
        """Generates the raw daily snapshot and derived monthly reports.

        Args:
            reference_date: The day used as the upper bound of the rolling
                reporting window.

        Returns:
            Metadata describing the written raw snapshot and derived reports.
        """
        window = rolling_window(reference_date)
        generated_at = datetime.now(self._timezone)
        worklogs = self._fetch_sorted_worklogs(window)
        snapshot = DailyRawSnapshot(
            space=self._space,
            snapshot_date=reference_date,
            window=window,
            generated_at=generated_at,
            timezone_name=self._timezone_name,
            worklogs=tuple(worklogs),
        )
        snapshot_path = self._report_storage.write_json(
            _daily_snapshot_path(self._space, reference_date),
            serialize_daily_snapshot(snapshot),
        )
        monthly_paths, curated_paths, _ = self._write_monthly_reports(
            months=months_in_range(window),
            worklogs=worklogs,
            generated_at=generated_at,
        )
        logger.info(
            "Generated snapshot for space {} with {} worklogs across {} month(s).",
            self._space.slug,
            len(worklogs),
            len(monthly_paths),
        )
        return DailySnapshotResult(
            snapshot_path,
            monthly_paths,
            curated_paths,
            len(worklogs),
        )


class MonthlyReportService(_BaseMonthlyReportService):
    """Builds a single derived monthly report on demand."""

    def __init__(
        self,
        source: WorklogSource,
        report_storage: JsonReportStorage,
        dataset_storage: CuratedDatasetStorage,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes the service with its reporting dependencies."""
        super().__init__(
            source=source,
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            timezone_name=timezone_name,
        )

    def generate(self, month: MonthId) -> MonthlyReportResult:
        """Generates one monthly report for the requested month."""
        window = month_range(month)
        generated_at = datetime.now(self._timezone)
        worklogs = self._fetch_sorted_worklogs(window)
        report_paths, curated_paths, reports = self._write_monthly_reports(
            months=(month,),
            worklogs=worklogs,
            generated_at=generated_at,
        )
        report = reports[0]
        ticket_count = len(report.tickets)
        return MonthlyReportResult(
            report_paths[0],
            curated_paths[0],
            ticket_count,
            len(worklogs),
        )


class BackfillService(_BaseMonthlyReportService):
    """Builds monthly reports for an explicit historical date range."""

    def __init__(
        self,
        source: WorklogSource,
        report_storage: JsonReportStorage,
        dataset_storage: CuratedDatasetStorage,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes the service with its reporting dependencies."""
        super().__init__(
            source=source,
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            timezone_name=timezone_name,
        )

    def generate(self, window: DateRange) -> BackfillResult:
        """Generates monthly reports for every month touched by the range."""
        generated_at = datetime.now(self._timezone)
        worklogs = self._fetch_sorted_worklogs(window)
        logger.info(
            "Starting historical backfill for space {} in range {} to {}.",
            self._space.slug,
            window.start.isoformat(),
            window.end.isoformat(),
        )
        monthly_paths, curated_paths, _ = self._write_monthly_reports(
            months=months_in_range(window),
            worklogs=worklogs,
            generated_at=generated_at,
        )
        logger.info(
            ("Completed historical backfill for space {} with {} worklogs across {} month(s)."),
            self._space.slug,
            len(worklogs),
            len(monthly_paths),
        )
        return BackfillResult(
            tuple(monthly_paths),
            tuple(curated_paths),
            len(worklogs),
            len(monthly_paths),
        )


class SheetsSyncService(_BaseSourceService):
    """Publishes the current daily reporting snapshot to yearly spreadsheets."""

    def __init__(
        self,
        source: WorklogSource,
        publisher: SpreadsheetPublisher,
        resolver: SpreadsheetResolver,
        space: JiraSpace,
        timezone_name: str,
    ) -> None:
        """Initializes the service with its reporting and publishing ports."""
        super().__init__(source=source, space=space, timezone_name=timezone_name)
        self._publisher = publisher
        self._resolver = resolver

    def generate(self, reference_date: date) -> SpreadsheetSyncResult:
        """Builds the current snapshot and publishes it to yearly spreadsheets."""
        return self._sync_snapshot(
            snapshot_date=reference_date,
            window=rolling_window(reference_date),
            explicit_range=False,
        )

    def generate_range(self, window: DateRange) -> SpreadsheetSyncResult:
        """Builds a snapshot for an explicit range and publishes monthly raw tabs."""
        return self._sync_snapshot(
            snapshot_date=window.end,
            window=window,
            explicit_range=True,
        )

    def _sync_snapshot(
        self,
        snapshot_date: date,
        window: DateRange,
        explicit_range: bool,
    ) -> SpreadsheetSyncResult:
        """Builds and publishes a snapshot for either rolling or explicit windows."""
        self._log_sync_start(snapshot_date, window, explicit_range)
        snapshot = self._build_snapshot(snapshot_date=snapshot_date, window=window)
        urls = self._publish_yearly_requests(snapshot)
        self._log_sync_completion(
            worklog_count=len(snapshot.worklogs),
            spreadsheet_count=len(urls),
            explicit_range=explicit_range,
        )
        return SpreadsheetSyncResult(tuple(urls), len(snapshot.worklogs))

    def _log_sync_start(
        self,
        snapshot_date: date,
        window: DateRange,
        explicit_range: bool,
    ) -> None:
        """Logs the beginning of a Sheets synchronization run."""
        if explicit_range:
            logger.info(
                "Starting Google Sheets range sync for space {} in range {} to {}.",
                self._space.slug,
                window.start.isoformat(),
                window.end.isoformat(),
            )
            return
        logger.info(
            "Starting Google Sheets sync for space {} and reference date {}.",
            self._space.slug,
            snapshot_date.isoformat(),
        )

    def _log_sync_completion(
        self,
        worklog_count: int,
        spreadsheet_count: int,
        explicit_range: bool,
    ) -> None:
        """Logs the end of a Sheets synchronization run."""
        if explicit_range:
            logger.info(
                ("Published {} worklogs to {} spreadsheet(s) for explicit range in space {}."),
                worklog_count,
                spreadsheet_count,
                self._space.slug,
            )
            logger.info(
                "Completed Google Sheets range sync for space {}.",
                self._space.slug,
            )
            return
        logger.info(
            "Published {} worklogs to {} spreadsheet(s) for space {}.",
            worklog_count,
            spreadsheet_count,
            self._space.slug,
        )
        logger.info(
            "Completed Google Sheets sync for space {}.",
            self._space.slug,
        )

    def _publish_yearly_requests(self, snapshot: DailyRawSnapshot) -> list[str]:
        """Builds and publishes every yearly spreadsheet payload for the snapshot."""
        urls: list[str] = []
        for year in years_for_snapshot(snapshot):
            target = self._resolver.resolve(year)
            logger.info(
                "Publishing space {} to spreadsheet {} for year {}.",
                self._space.slug,
                target.spreadsheet_id,
                year,
            )
            request = build_spreadsheet_request(
                snapshot=snapshot,
                spreadsheet_id=target.spreadsheet_id,
                year=year,
            )
            urls.append(self._publisher.publish(request))
            logger.info(
                "Completed spreadsheet publish for space {} year {}.",
                self._space.slug,
                year,
            )
        return urls


class BigQuerySyncService:
    """Loads curated monthly worklogs into BigQuery for active reporting months."""

    def __init__(
        self,
        dataset_storage: CuratedDatasetStorage,
        warehouse: WorklogWarehouse,
        space: JiraSpace,
    ) -> None:
        """Initializes the service with storage and reporting warehouse ports."""
        self._dataset_storage = dataset_storage
        self._warehouse = warehouse
        self._space = space

    def generate(self, reference_date: date) -> BigQuerySyncResult:
        """Loads the active operational months into BigQuery."""
        months = active_months(reference_date)
        return self._sync_months(months)

    def generate_range(self, window: DateRange) -> BigQuerySyncResult:
        """Loads every month touched by an explicit historical range."""
        months = months_in_range(window)
        return self._sync_months(months)

    def _sync_months(self, months: tuple[MonthId, ...]) -> BigQuerySyncResult:
        logger.info(
            "Starting BigQuery sync for space {} across {} month(s).",
            self._space.slug,
            len(months),
        )
        worklog_count = 0
        for month in months:
            payload = self._dataset_storage.read_bytes(_monthly_worklogs_path(self._space, month))
            worklog_count += count_parquet_rows(payload)
            self._warehouse.load_monthly_worklogs(self._space, month, payload)
            logger.info(
                "Loaded curated worklogs for space {} month {} into BigQuery.",
                self._space.slug,
                month.label(),
            )
        self._warehouse.ensure_views()
        logger.info("Completed BigQuery sync for space {}.", self._space.slug)
        return BigQuerySyncResult(months, worklog_count)


def _build_monthly_report(
    worklogs: list[WorklogEntry],
    space: JiraSpace,
    month: MonthId,
    generated_at: datetime,
    timezone_name: str,
) -> MonthlyWorklogReport:
    """Builds a monthly report by grouping worklogs per ticket."""
    relevant = _worklogs_for_month(worklogs, month)
    tickets: dict[tuple[str, str, str], list[WorklogEntry]] = {}
    for entry in relevant:
        key = (entry.issue_key, entry.issue_summary, entry.issue_type)
        tickets.setdefault(key, []).append(entry)
    ticket_reports = tuple(
        TicketWorklogReport(
            issue_key=issue_key,
            summary=summary,
            issue_type=issue_type,
            bookings=tuple(_sort_worklogs(entries)),
        )
        for issue_key, summary, issue_type, entries in _sorted_tickets(tickets)
    )
    return MonthlyWorklogReport(
        space=space,
        month=month,
        generated_at=generated_at,
        timezone_name=timezone_name,
        tickets=ticket_reports,
    )


def _fetch_sorted_worklogs(
    source: WorklogSource,
    window: DateRange,
) -> list[WorklogEntry]:
    """Fetches worklogs for a window and sorts them deterministically."""
    return _sort_worklogs(source.fetch_worklogs(window))


def _build_snapshot_for_window(
    source: WorklogSource,
    space: JiraSpace,
    snapshot_date: date,
    window: DateRange,
    timezone: ZoneInfo,
    timezone_name: str,
) -> DailyRawSnapshot:
    """Builds an in-memory snapshot for either operational or explicit windows."""
    generated_at = datetime.now(timezone)
    worklogs = _fetch_sorted_worklogs(source, window)
    return DailyRawSnapshot(
        space=space,
        snapshot_date=snapshot_date,
        window=window,
        generated_at=generated_at,
        timezone_name=timezone_name,
        worklogs=tuple(worklogs),
    )


def _write_monthly_reports(
    report_storage: JsonReportStorage,
    dataset_storage: CuratedDatasetStorage,
    space: JiraSpace,
    months: tuple[MonthId, ...],
    worklogs: list[WorklogEntry],
    generated_at: datetime,
    timezone_name: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[MonthlyWorklogReport, ...]]:
    """Writes derived monthly reports and curated datasets for requested months."""
    report_paths: list[str] = []
    curated_paths: list[str] = []
    reports: list[MonthlyWorklogReport] = []
    for month in months:
        report_path, curated_path, report = _write_monthly_report(
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            month=month,
            worklogs=worklogs,
            generated_at=generated_at,
            timezone_name=timezone_name,
        )
        report_paths.append(report_path)
        curated_paths.append(curated_path)
        reports.append(report)
    return tuple(report_paths), tuple(curated_paths), tuple(reports)


def _write_monthly_report(
    report_storage: JsonReportStorage,
    dataset_storage: CuratedDatasetStorage,
    space: JiraSpace,
    month: MonthId,
    worklogs: list[WorklogEntry],
    generated_at: datetime,
    timezone_name: str,
) -> tuple[str, str, MonthlyWorklogReport]:
    """Writes one derived monthly report and curated dataset."""
    monthly_worklogs = _worklogs_for_month(worklogs, month)
    report = _build_monthly_report(
        monthly_worklogs,
        space,
        month,
        generated_at,
        timezone_name,
    )
    report_path = report_storage.write_json(
        _monthly_report_path(space, month),
        serialize_monthly_report(report),
    )
    curated_path = dataset_storage.write_parquet(
        _monthly_worklogs_path(space, month),
        serialize_monthly_worklogs(space, month, monthly_worklogs),
    )
    return report_path, curated_path, report


def _sorted_tickets(
    tickets: dict[tuple[str, str, str], list[WorklogEntry]],
) -> list[tuple[str, str, str, list[WorklogEntry]]]:
    """Returns grouped tickets sorted by issue key."""
    items = [(issue_key, summary, issue_type, entries) for (issue_key, summary, issue_type), entries in tickets.items()]
    return sorted(items, key=lambda item: (item[0], item[1], item[2]))


def _sort_worklogs(worklogs: list[WorklogEntry]) -> list[WorklogEntry]:
    """Returns worklogs sorted for deterministic output."""
    return sorted(
        worklogs,
        key=lambda item: (item.issue_key, item.started_at, item.worklog_id),
    )


def _worklogs_for_month(
    worklogs: list[WorklogEntry],
    month: MonthId,
) -> list[WorklogEntry]:
    """Returns only worklogs whose local start date belongs to the month."""
    return [entry for entry in worklogs if month.contains(entry.started_at.date())]


def _daily_snapshot_path(space: JiraSpace, reference_date: date) -> str:
    """Builds the storage path for a raw daily snapshot."""
    return f"spaces/{space.key}/{space.slug}/raw/daily/{reference_date:%Y/%m/%Y-%m-%d}.json"


def _monthly_report_path(space: JiraSpace, month: MonthId) -> str:
    """Builds the storage path for a derived monthly report."""
    return f"spaces/{space.key}/{space.slug}/derived/monthly/{month.year:04d}/{month.label()}.json"


def _monthly_worklogs_path(space: JiraSpace, month: MonthId) -> str:
    """Builds the storage path for a curated monthly worklog dataset."""
    return f"curated/worklogs/space={space.slug}/year={month.year:04d}/month={month.month:02d}/worklogs.parquet"
