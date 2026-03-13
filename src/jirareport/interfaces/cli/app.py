from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

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
    CuratedDatasetStorage,
    JsonReportStorage,
    SpreadsheetPublisher,
    SpreadsheetResolver,
    WorklogSource,
    WorklogWarehouse,
)
from jirareport.domain.time_range import current_date, explicit_range
from jirareport.infrastructure.config import AppSettings, load_settings
from jirareport.infrastructure.google.bigquery_client import BigQueryWorklogWarehouse
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
)
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.infrastructure.logging_config import configure_logging, flush_logging
from jirareport.infrastructure.storage import (
    build_curated_dataset_storage,
    build_json_report_storage,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI entrypoint and dispatches the selected command."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.debug)
    try:
        settings = load_settings()
        return _dispatch_command(args, settings)
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
            "  jirareport sync sheets --from 2025-01-01 --to 2025-12-31\n"
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
    _add_daily_parser(subparsers)
    _add_backfill_parser(subparsers)
    _add_monthly_parser(subparsers)
    _add_sync_parser(subparsers)
    return parser


def _add_daily_parser(subparsers: Any) -> None:
    """Registers the daily command parser."""
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


def _add_backfill_parser(
    subparsers: Any,
) -> None:
    """Registers the historical backfill command parser."""
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


def _add_monthly_parser(
    subparsers: Any,
) -> None:
    """Registers the ad hoc monthly command parser."""
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


def _add_sync_parser(subparsers: Any) -> None:
    """Registers synchronization targets."""
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
    _add_sync_sheets_parser(sync_subparsers)
    _add_sync_bigquery_parser(sync_subparsers)


def _add_sync_sheets_parser(
    subparsers: Any,
) -> None:
    """Registers the Google Sheets synchronization parser."""
    sheets = subparsers.add_parser(
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
        "--from",
        dest="from_date",
        type=str,
        help="Optional inclusive range start in YYYY-MM-DD format.",
    )
    sheets.add_argument(
        "--to",
        dest="to_date",
        type=str,
        help="Optional inclusive range end in YYYY-MM-DD format.",
    )
    sheets.add_argument(
        "--space",
        type=str,
        help="Optional Jira space key or slug. Defaults to all configured spaces.",
    )


def _add_sync_bigquery_parser(
    subparsers: Any,
) -> None:
    """Registers the BigQuery synchronization parser."""
    bigquery = subparsers.add_parser(
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


def _dispatch_command(args: argparse.Namespace, settings: AppSettings) -> int:
    """Dispatches the parsed CLI command."""
    if args.command == "daily":
        return _run_daily(
            args.date,
            args.space,
            settings,
            _build_source,
            _build_json_report_storage(settings),
            _build_curated_dataset_storage(settings),
        )
    if args.command == "backfill":
        return _run_backfill(
            args.from_date,
            args.to_date,
            args.space,
            settings,
            _build_source,
            _build_json_report_storage(settings),
            _build_curated_dataset_storage(settings),
        )
    if args.command == "monthly":
        return _run_monthly(
            args.month,
            args.space,
            settings,
            _build_source,
            _build_json_report_storage(settings),
            _build_curated_dataset_storage(settings),
        )
    return _dispatch_sync_command(args, settings)


def _dispatch_sync_command(args: argparse.Namespace, settings: AppSettings) -> int:
    """Dispatches synchronization subcommands."""
    if args.sync_target == "bigquery":
        return _run_sync_bigquery(
            args.date,
            args.from_date,
            args.to_date,
            args.space,
            settings,
            _build_curated_dataset_storage(settings),
            _build_worklog_warehouse(settings),
        )
    return _run_sync_sheets(
        args.date,
        args.from_date,
        args.to_date,
        args.space,
        settings,
        _build_source,
        _build_spreadsheet_publisher(settings),
    )


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


def _build_json_report_storage(settings: AppSettings) -> JsonReportStorage:
    """Builds the configured JSON report storage adapter."""
    return build_json_report_storage(
        settings.storage.backend,
        settings.storage.local_output_dir,
        settings.storage.bucket_name,
        settings.storage.bucket_prefix,
    )


def _build_curated_dataset_storage(settings: AppSettings) -> CuratedDatasetStorage:
    """Builds the configured curated dataset storage adapter."""
    return build_curated_dataset_storage(
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


def _build_worklog_warehouse(settings: AppSettings) -> WorklogWarehouse:
    """Builds the configured analytical worklog warehouse adapter."""
    if not settings.bigquery.enabled:
        raise ValueError("BigQuery reporting is disabled.")
    if settings.bigquery.project_id is None or settings.bigquery.dataset is None:
        raise ValueError("BigQuery project and dataset must be configured.")
    return BigQueryWorklogWarehouse(
        project_id=settings.bigquery.project_id,
        dataset=settings.bigquery.dataset,
        spaces=settings.spaces,
        table=settings.bigquery.table,
    )


def _build_spreadsheet_resolver(
    settings: AppSettings,
    space: JiraSpace,
) -> SpreadsheetResolver:
    """Builds the configured yearly spreadsheet resolver."""
    if not settings.sheets.enabled:
        raise ValueError("Google Sheets publishing is disabled.")
    configured_space = settings.configured_space(space)
    return GoogleSheetsResolver(
        spreadsheet_ids=configured_space.google_sheets_id_map(),
        title_prefix=f"{settings.sheets.title_prefix} - {space.name}",
    )


def _resolve_reference_date(
    input_date: str | None,
    timezone_name: str,
) -> date:
    """Resolves a CLI date or falls back to the current reporting date."""
    if input_date:
        return date.fromisoformat(input_date)
    return current_date(timezone_name)


def _resolve_reference_date_or_window(
    input_date: str | None,
    input_from: str | None,
    input_to: str | None,
    timezone_name: str,
    command_label: str,
) -> tuple[date | None, DateRange | None]:
    """Resolves either an operational reference date or an explicit range."""
    explicit_window = _explicit_window_optional(input_from, input_to)
    if input_date and explicit_window is not None:
        raise ValueError(f"Use either --date or --from/--to for {command_label}.")
    if explicit_window is not None:
        return None, explicit_window
    return _resolve_reference_date(input_date, timezone_name), None


def _run_for_selected_spaces(
    settings: AppSettings,
    selector: str | None,
    runner: Callable[[JiraSpace], None],
) -> None:
    """Executes one callback for every selected reporting space."""
    for space in _selected_spaces(settings, selector):
        runner(space)


def _run_daily(
    input_date: str | None,
    space_selector: str | None,
    settings: AppSettings,
    source_builder: Callable[[AppSettings, JiraSpace], WorklogSource],
    report_storage: JsonReportStorage,
    dataset_storage: CuratedDatasetStorage,
) -> int:
    """Runs the main daily use case."""
    reference_date = _resolve_reference_date(input_date, settings.timezone_name)

    def run_for_space(space: JiraSpace) -> None:
        service = DailySnapshotService(
            source=source_builder(settings, space),
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(reference_date)
        logger.info(
            (
                "Daily snapshot for {} saved to {} "
                "with {} worklogs across {} curated month(s)."
            ),
            space.slug,
            result.snapshot_path,
            result.worklog_count,
            len(result.curated_paths),
        )

    _run_for_selected_spaces(settings, space_selector, run_for_space)
    logger.info("Completed daily snapshot command.")
    return 0


def _run_backfill(
    input_from: str,
    input_to: str,
    space_selector: str | None,
    settings: AppSettings,
    source_builder: Callable[[AppSettings, JiraSpace], WorklogSource],
    report_storage: JsonReportStorage,
    dataset_storage: CuratedDatasetStorage,
) -> int:
    """Runs the historical backfill use case for an explicit range."""
    window = _explicit_window(input_from, input_to)

    def run_for_space(space: JiraSpace) -> None:
        service = BackfillService(
            source=source_builder(settings, space),
            report_storage=report_storage,
            dataset_storage=dataset_storage,
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

    _run_for_selected_spaces(settings, space_selector, run_for_space)
    logger.info("Completed historical backfill command.")
    return 0


def _run_monthly(
    input_month: str | None,
    space_selector: str | None,
    settings: AppSettings,
    source_builder: Callable[[AppSettings, JiraSpace], WorklogSource],
    report_storage: JsonReportStorage,
    dataset_storage: CuratedDatasetStorage,
) -> int:
    """Runs the ad hoc monthly report generation use case."""
    month = (
        MonthId.parse(input_month)
        if input_month
        else MonthId.from_date(current_date(settings.timezone_name))
    )

    def run_for_space(space: JiraSpace) -> None:
        service = MonthlyReportService(
            source=source_builder(settings, space),
            report_storage=report_storage,
            dataset_storage=dataset_storage,
            space=space,
            timezone_name=settings.timezone_name,
        )
        result = service.generate(month)
        logger.info(
            "Monthly report for {} saved to {}",
            space.slug,
            result.report_path,
        )

    _run_for_selected_spaces(settings, space_selector, run_for_space)
    logger.info("Completed monthly report command.")
    return 0


def _run_sync_sheets(
    input_date: str | None,
    input_from: str | None,
    input_to: str | None,
    space_selector: str | None,
    settings: AppSettings,
    source_builder: Callable[[AppSettings, JiraSpace], WorklogSource],
    publisher: SpreadsheetPublisher,
) -> int:
    """Runs the Google Sheets synchronization use case."""
    reference_date, explicit_window = _resolve_reference_date_or_window(
        input_date=input_date,
        input_from=input_from,
        input_to=input_to,
        timezone_name=settings.timezone_name,
        command_label="Google Sheets sync",
    )

    def run_for_space(space: JiraSpace) -> None:
        service = SheetsSyncService(
            source=source_builder(settings, space),
            publisher=publisher,
            resolver=_build_spreadsheet_resolver(settings, space),
            space=space,
            timezone_name=settings.timezone_name,
        )
        if explicit_window is None:
            assert reference_date is not None
            result = service.generate(reference_date)
        else:
            result = service.generate_range(explicit_window)
        logger.info(
            "Published Google Sheets sync for {} to {} with {} worklogs.",
            space.slug,
            ", ".join(result.spreadsheet_urls),
            result.worklog_count,
        )

    _run_for_selected_spaces(settings, space_selector, run_for_space)
    logger.info("Completed Google Sheets sync command.")
    return 0


def _run_sync_bigquery(
    input_date: str | None,
    input_from: str | None,
    input_to: str | None,
    space_selector: str | None,
    settings: AppSettings,
    dataset_storage: CuratedDatasetStorage,
    warehouse: WorklogWarehouse,
) -> int:
    """Runs the BigQuery synchronization use case."""
    reference_date, explicit_window = _resolve_reference_date_or_window(
        input_date=input_date,
        input_from=input_from,
        input_to=input_to,
        timezone_name=settings.timezone_name,
        command_label="BigQuery sync",
    )

    def run_for_space(space: JiraSpace) -> None:
        service = BigQuerySyncService(
            dataset_storage=dataset_storage,
            warehouse=warehouse,
            space=space,
        )
        if explicit_window is None:
            assert reference_date is not None
            result = service.generate(reference_date)
        else:
            result = service.generate_range(explicit_window)
        logger.info(
            "Published BigQuery sync for {} across month(s): {} with {} worklogs.",
            space.slug,
            ", ".join(month.label() for month in result.months),
            result.worklog_count,
        )

    _run_for_selected_spaces(settings, space_selector, run_for_space)
    logger.info("Completed BigQuery sync command.")
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
    """Returns either all configured spaces or one selected by key or slug."""
    if selector in {None, ""}:
        return settings.spaces
    for space in settings.spaces:
        if selector in {space.key, space.slug}:
            return (space,)
    raise ValueError(f"Unknown Jira space selector: {selector}")
