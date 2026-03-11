from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from loguru import logger

from jirareport.application.services import (
    DailySnapshotService,
    MonthlyReportService,
    SheetsSyncService,
)
from jirareport.domain.models import MonthId
from jirareport.domain.ports import ReportStorage, SpreadsheetPublisher, WorklogSource
from jirareport.domain.time_range import current_date
from jirareport.infrastructure.config import AppSettings, load_settings
from jirareport.infrastructure.google.sheets_client import GoogleSheetsPublisher
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.infrastructure.logging_config import configure_logging
from jirareport.infrastructure.storage import build_storage


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI entrypoint and dispatches the selected command."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.debug)
    settings = load_settings()
    if args.command == "daily":
        source = _build_source(settings)
        storage = _build_storage(settings)
        return _run_daily(args.date, settings, source, storage)
    if args.command == "monthly":
        source = _build_source(settings)
        storage = _build_storage(settings)
        return _run_monthly(args.month, settings, source, storage)
    source = _build_source(settings)
    publisher = _build_spreadsheet_publisher(settings)
    return _run_sync_sheets(args.date, settings, source, publisher)


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
            "  jirareport monthly\n"
            "  jirareport monthly --month 2026-03\n"
            "  jirareport sync sheets\n"
            "  jirareport sync sheets --date 2026-03-11"
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
        metavar="{daily,monthly,sync}",
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
    sync = subparsers.add_parser(
        "sync",
        help="Synchronize reporting data to external publishing targets.",
    )
    sync_subparsers = sync.add_subparsers(
        dest="sync_target",
        required=True,
        title="targets",
        metavar="{sheets}",
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
    return parser


def _build_source(settings: AppSettings) -> WorklogSource:
    """Builds the configured worklog source adapter."""
    jira = settings.jira
    return JiraWorklogSource(
        base_url=jira.base_url,
        email=jira.email,
        api_token=jira.api_token,
        project_key=jira.project_key,
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


def _run_daily(
    input_date: str | None,
    settings: AppSettings,
    source: WorklogSource,
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
    service = DailySnapshotService(
        source=source,
        storage=storage,
        project_key=settings.jira.project_key,
        timezone_name=settings.timezone_name,
    )
    result = service.generate(reference_date)
    logger.info("Daily snapshot saved to {}", result.snapshot_path)
    return 0


def _run_monthly(
    input_month: str | None,
    settings: AppSettings,
    source: WorklogSource,
    storage: ReportStorage,
) -> int:
    """Runs the ad hoc monthly report generation use case."""
    if input_month:
        month = MonthId.parse(input_month)
    else:
        month = MonthId.from_date(current_date(settings.timezone_name))
    service = MonthlyReportService(
        source=source,
        storage=storage,
        project_key=settings.jira.project_key,
        timezone_name=settings.timezone_name,
    )
    result = service.generate(month)
    logger.info("Monthly report saved to {}", result.report_path)
    return 0


def _run_sync_sheets(
    input_date: str | None,
    settings: AppSettings,
    source: WorklogSource,
    publisher: SpreadsheetPublisher,
) -> int:
    """Runs the Google Sheets synchronization use case."""
    if input_date:
        reference_date = date.fromisoformat(input_date)
    else:
        reference_date = current_date(settings.timezone_name)
    service = SheetsSyncService(
        source=source,
        publisher=publisher,
        project_key=settings.jira.project_key,
        spreadsheet_ids=settings.sheets.spreadsheet_ids,
        timezone_name=settings.timezone_name,
    )
    result = service.generate(reference_date)
    logger.info(
        "Published Google Sheets sync to {}",
        ", ".join(result.spreadsheet_urls),
    )
    return 0
