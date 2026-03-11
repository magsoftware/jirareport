from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date

from loguru import logger

from jirareport.application.services import DailySnapshotService, MonthlyReportService
from jirareport.domain.models import MonthId
from jirareport.domain.ports import ReportStorage, WorklogSource
from jirareport.domain.time_range import current_date
from jirareport.infrastructure.config import AppSettings, load_settings
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.infrastructure.logging_config import configure_logging
from jirareport.infrastructure.storage import build_storage


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.debug)
    settings = load_settings()
    source = _build_source(settings)
    storage = build_storage(
        settings.storage.backend,
        settings.storage.local_output_dir,
        settings.storage.bucket_name,
        settings.storage.bucket_prefix,
    )
    if args.command == "daily":
        return _run_daily(args.date, settings, source, storage)
    return _run_monthly(args.month, settings, source, storage)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Jira worklog reports.")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily", help="Generate daily raw snapshot.")
    daily.add_argument("--date", type=str, help="Snapshot date in YYYY-MM-DD format.")
    monthly = subparsers.add_parser("monthly", help="Generate monthly report.")
    monthly.add_argument("--month", type=str, help="Target month in YYYY-MM format.")
    return parser


def _build_source(settings: AppSettings) -> WorklogSource:
    jira = settings.jira
    return JiraWorklogSource(
        base_url=jira.base_url,
        email=jira.email,
        api_token=jira.api_token,
        project_key=jira.project_key,
        timezone_name=settings.timezone_name,
    )


def _run_daily(
    input_date: str | None,
    settings: AppSettings,
    source: WorklogSource,
    storage: ReportStorage,
) -> int:
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
