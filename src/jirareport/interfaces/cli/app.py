from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from loguru import logger

from jirareport.application.services import (
    BackfillService,
    BigQuerySyncService,
    DailySnapshotService,
    MonthlyReportService,
    SheetsSyncService,
)
from jirareport.domain.models import DateRange, JiraSpace, MonthId
from jirareport.domain.ports import (
    ReportingWarehouse,
    ReportStorage,
    SpreadsheetPublisher,
    SpreadsheetResolver,
    WorklogSource,
)
from jirareport.domain.time_range import current_date, explicit_range
from jirareport.infrastructure.config import AppSettings, load_settings
from jirareport.infrastructure.google.bigquery_client import BigQueryWarehouse
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
)
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.infrastructure.logging_config import configure_logging, flush_logging
from jirareport.infrastructure.storage import build_storage


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI entrypoint and dispatches the selected command."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.debug)
    try:
        settings = load_settings()
        if args.command == "daily":
            storage = _build_storage(settings)
            return _run_daily(args.date, args.space, settings, storage)
        if args.command == "backfill":
            storage = _build_storage(settings)
            return _run_backfill(
                args.from_date,
                args.to_date,
                args.space,
                settings,
                storage,
            )
        if args.command == "monthly":
            storage = _build_storage(settings)
            return _run_monthly(args.month, args.space, settings, storage)
        if args.sync_target == "bigquery":
            storage = _build_storage(settings)
            warehouse = _build_reporting_warehouse(settings)
            return _run_sync_bigquery(
                args.date,
                args.from_date,
                args.to_date,
                args.space,
                settings,
                storage,
                warehouse,
            )
        publisher = _build_spreadsheet_publisher(settings)
        return _run_sync_sheets(args.date, args.space, settings, publisher)
    finally:
        flush_logging()


def _build_parser() -> argparse.ArgumentParser:
    """Builds the top-level CLI parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate Jira worklog reports as JSON files. "
            "The daily command creates a raw snapshot and refreshes "
            "monthly derived reports for the rolling window."
        ),
        epilog=(
            "Examples:\n"
            "  jirareport daily\n"
            "  jirareport daily --date 2026-03-11\n"
            "  jirareport backfill --from 2025-01-01 --to 2025-12-31\n"
            "  jirareport monthly\n"
            "  jirareport monthly --month 2026-03\n"
            "  jirareport sync sheets\n"
            "  jirareport sync sheets --date 2026-03-11\n"
            "  jirareport sync bigquery --date 2026-03-11"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging, including the exact JQL sent to Jira.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="{daily,backfill,monthly,sync}",
    )
    daily = subparsers.add_parser(
        "daily",
        help="Generate a daily raw snapshot and refresh derived monthly reports.",
        description=(
            "Generate a raw snapshot for the given day and rebuild derived "
            "monthly reports for all months covered by the rolling window."
        ),
    )
    daily.add_argument(
        "--date",
        type=str,
        help=(
            "Reference date in YYYY-MM-DD format. "
            "Defaults to the current date in REPORT_TIMEZONE."
        ),
    )
    daily.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )
    backfill = subparsers.add_parser(
        "backfill",
        help="Generate monthly reports for an explicit historical date range.",
        description=(
            "Fetch worklogs for the requested date range and rebuild every "
            "monthly report touched by that range."
        ),
    )
    backfill.add_argument(
        "--from",
        dest="from_date",
        required=True,
        type=str,
        help="Inclusive range start in YYYY-MM-DD format.",
    )
    backfill.add_argument(
        "--to",
        dest="to_date",
        required=True,
        type=str,
        help="Inclusive range end in YYYY-MM-DD format.",
    )
    backfill.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )
    monthly = subparsers.add_parser(
        "monthly",
        help="Generate a derived report for a single target month.",
        description=(
            "Generate a monthly report for a single calendar month "
            "without creating a daily raw snapshot."
        ),
    )
    monthly.add_argument(
        "--month",
        type=str,
        help=(
            "Target month in YYYY-MM format. "
            "Defaults to the current month in REPORT_TIMEZONE."
        ),
    )
    monthly.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )
    sync = subparsers.add_parser(
        "sync",
        help="Synchronize reporting data to external publishing targets.",
    )
    sync_subparsers = sync.add_subparsers(
        dest="sync_target",
        required=True,
        title="targets",
        metavar="{sheets,bigquery}",
    )
    sheets = sync_subparsers.add_parser(
        "sheets",
        help="Publish the current daily reporting snapshot to Google Sheets.",
        description=(
            "Build the current rolling daily snapshot in memory and publish it "
            "to the configured yearly Google Sheets workbook(s)."
        ),
    )
    sheets.add_argument(
        "--date",
        type=str,
        help=(
            "Reference date in YYYY-MM-DD format. "
            "Defaults to the current date in REPORT_TIMEZONE."
        ),
    )
    sheets.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )
    bigquery = sync_subparsers.add_parser(
        "bigquery",
        help="Load curated monthly worklogs into BigQuery and refresh views.",
        description=(
            "Loads curated monthly worklogs into BigQuery for either the "
            "operational reporting window or an explicit historical range."
        ),
    )
    bigquery.add_argument(
        "--date",
        type=str,
        help=(
            "Operational reference date in YYYY-MM-DD format. "
            "Defaults to the current date in REPORT_TIMEZONE."
        ),
    )
    bigquery.add_argument(
        "--from",
        dest="from_date",
        type=str,
        help="Optional inclusive range start in YYYY-MM-DD format.",
    )
    bigquery.add_argument(
        "--to",
        dest="to_date",
        type=str,
        help="Optional inclusive range end in YYYY-MM-DD format.",
    )
    bigquery.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )
    return parser


def _build_source(settings: AppSettings, space: JiraSpace) -> WorklogSource:
    """Builds the configured worklog source adapter."""
    jira = settings.jira
    return JiraWorklogSource(
        base_url=jira.base_url,
        email=jira.email,
        api_token=jira.api_token,
        project_key=space.key,
        timezone_name=settings.timezone_name,
    )


def _build_storage(settings: AppSettings) -> ReportStorage:
    """Builds the configured report storage adapter."""
    return build_storage(
        settings.storage.backend,
        settings.storage.local_output_dir,
        settings.storage.bucket_name,
        settings.storage.bucket_prefix,
    )


def _build_spreadsheet_publisher(settings: AppSettings) -> SpreadsheetPublisher:
    """Builds the configured Google Sheets publisher adapter."""
    if not settings.sheets.enabled:
        raise ValueError("Google Sheets publishing is disabled.")
    return GoogleSheetsPublisher()


def _build_reporting_warehouse(settings: AppSettings) -> ReportingWarehouse:
    """Builds the configured BigQuery reporting warehouse adapter."""
    if not settings.bigquery.enabled:
        raise ValueError("BigQuery reporting is disabled.")
    if settings.bigquery.project_id is None or settings.bigquery.dataset is None:
        raise ValueError("BigQuery project and dataset must be configured.")
    return BigQueryWarehouse(
        project_id=settings.bigquery.project_id,
        dataset=settings.bigquery.dataset,
        table=settings.bigquery.table,
    )


def _build_spreadsheet_resolver(
    settings: AppSettings,
    space: JiraSpace,
) -> SpreadsheetResolver:
    """Builds the configured yearly spreadsheet resolver."""
    if not settings.sheets.enabled:
        raise ValueError("Google Sheets publishing is disabled.")
    return GoogleSheetsResolver(
        spreadsheet_ids=dict(space.safe_google_sheets_ids),
        title_prefix=f"{settings.sheets.title_prefix} - {space.name}",
    )


def _run_daily(
    input_date: str | None,
    space_selector: str | None,
    settings: AppSettings,
    storage: ReportStorage,
) -> int:
    """Runs the main daily use case.

    This command is the primary operational flow of the tool. It generates a
    raw daily snapshot and refreshes all derived monthly reports affected by
    the rolling reporting window.
    """
    if input_date:
        reference_date = date.fromisoformat(input_date)
    else:
        reference_date = current_date(settings.timezone_name)
    for space in _selected_spaces(settings, space_selector):
        source = _build_source(settings, space)
        service = DailySnapshotService(
            source=source,
            storage=storage,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(reference_date)
        logger.info(
            "Daily snapshot for {} saved to {}",
            space.slug,
            result.snapshot_path,
        )
    logger.info("Completed daily snapshot command.")
    flush_logging()
    return 0


def _run_backfill(
    input_from: str,
    input_to: str,
    space_selector: str | None,
    settings: AppSettings,
    storage: ReportStorage,
) -> int:
    """Runs the historical backfill use case for an explicit range."""
    window = _explicit_window(input_from, input_to)
    for space in _selected_spaces(settings, space_selector):
        source = _build_source(settings, space)
        service = BackfillService(
            source=source,
            storage=storage,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(window)
        logger.info(
            (
                "Historical backfill for {} produced {} "
                "monthly report(s) from {} worklogs."
            ),
            space.slug,
            result.month_count,
            result.worklog_count,
        )
    logger.info("Completed historical backfill command.")
    flush_logging()
    return 0


def _run_monthly(
    input_month: str | None,
    space_selector: str | None,
    settings: AppSettings,
    storage: ReportStorage,
) -> int:
    """Runs the ad hoc monthly report generation use case."""
    if input_month:
        month = MonthId.parse(input_month)
    else:
        month = MonthId.from_date(current_date(settings.timezone_name))
    for space in _selected_spaces(settings, space_selector):
        source = _build_source(settings, space)
        service = MonthlyReportService(
            source=source,
            storage=storage,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(month)
        logger.info(
            "Monthly report for {} saved to {}",
            space.slug,
            result.report_path,
        )
    logger.info("Completed monthly report command.")
    flush_logging()
    return 0


def _run_sync_sheets(
    input_date: str | None,
    space_selector: str | None,
    settings: AppSettings,
    publisher: SpreadsheetPublisher,
) -> int:
    """Runs the Google Sheets synchronization use case."""
    if input_date:
        reference_date = date.fromisoformat(input_date)
    else:
        reference_date = current_date(settings.timezone_name)
    for space in _selected_spaces(settings, space_selector):
        source = _build_source(settings, space)
        resolver = _build_spreadsheet_resolver(settings, space)
        service = SheetsSyncService(
            source=source,
            publisher=publisher,
            resolver=resolver,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(reference_date)
        logger.info(
            "Published Google Sheets sync for {} to {}",
            space.slug,
            ", ".join(result.spreadsheet_urls),
        )
    logger.info("Completed Google Sheets sync command.")
    flush_logging()
    return 0


def _run_sync_bigquery(
    input_date: str | None,
    input_from: str | None,
    input_to: str | None,
    space_selector: str | None,
    settings: AppSettings,
    storage: ReportStorage,
    warehouse: ReportingWarehouse,
) -> int:
    """Runs the BigQuery synchronization use case."""
    explicit_window = _explicit_window_optional(input_from, input_to)
    if input_date and explicit_window is not None:
        raise ValueError("Use either --date or --from/--to for BigQuery sync.")
    if explicit_window is None:
        if input_date:
            reference_date = date.fromisoformat(input_date)
        else:
            reference_date = current_date(settings.timezone_name)
    for space in _selected_spaces(settings, space_selector):
        service = BigQuerySyncService(
            storage=storage,
            warehouse=warehouse,
            space=space,
        )
        if explicit_window is None:
            result = service.generate(reference_date)
        else:
            result = service.generate_range(explicit_window)
        logger.info(
            "Published BigQuery sync for {} across month(s): {}",
            space.slug,
            ", ".join(month.label() for month in result.months),
        )
    logger.info("Completed BigQuery sync command.")
    flush_logging()
    return 0


def _explicit_window(input_from: str, input_to: str) -> DateRange:
    """Parses an explicit inclusive date range from CLI arguments."""
    return explicit_range(
        start=date.fromisoformat(input_from),
        end=date.fromisoformat(input_to),
    )


def _explicit_window_optional(
    input_from: str | None,
    input_to: str | None,
) -> DateRange | None:
    """Returns an explicit range when both boundaries are provided."""
    if input_from is None and input_to is None:
        return None
    if input_from is None or input_to is None:
        raise ValueError("Both --from and --to are required for an explicit range.")
    return _explicit_window(input_from, input_to)


def _selected_spaces(
    settings: AppSettings,
    selector: str | None,
) -> tuple[JiraSpace, ...]:
    """Returns either all configured spaces or one selected by key/slug."""
    if selector in {None, ""}:
        return settings.spaces
    for space in settings.spaces:
        if selector in {space.key, space.slug}:
            return (space,)
    raise ValueError(f"Unknown Jira space selector: {selector}")
