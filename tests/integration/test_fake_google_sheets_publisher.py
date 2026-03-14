"""Integration scenarios for the Google Sheets publisher and resolver.

Goal
- Validate the real Google Sheets adapters against a stateful in-memory fake
  Sheets service that stores worksheets, rows, and created spreadsheets.
- Prove that reruns replace worksheet contents and that missing yearly
  spreadsheets can be created and reused.

Fixtures
- `StatefulFakeSheetsService` stores spreadsheet metadata and final worksheet
  rows after `clear`, `update`, and `batchUpdate` operations.
- Real `GoogleSheetsPublisher` and `GoogleSheetsResolver` are used so the tests
  exercise actual publishing logic and resolver behavior.
- Worksheet payloads mimic the monthly raw sheets produced by the reporting
  pipeline, including the new `issue_type` column.

Scenarios
1. Publishing the same monthly worksheet twice replaces previous rows rather
   than appending, which mirrors nightly reruns.
2. Resolving a missing year creates a new spreadsheet that can be immediately
   used by the publisher.
"""

from __future__ import annotations

from typing import cast

from jirareport.domain.models import (
    SheetCellValue,
    SpreadsheetPublishRequest,
    WorksheetData,
)
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
    SheetsServiceProtocol,
)
from tests.fakes.fake_sheets import StatefulFakeSheetsService


def test_publisher_rerun_replaces_existing_month_rows() -> None:
    """Scenario
    Given an existing yearly spreadsheet with one monthly worksheet
    When the publisher uploads the same worksheet a second time with new rows
    Then the stored worksheet rows are replaced instead of being appended.
    """

    service = StatefulFakeSheetsService()
    service.add_spreadsheet(
        "cp-2026",
        title="Jira Worklog Analytics - Click Price 2026",
        worksheet_titles=("03",),
    )
    publisher = GoogleSheetsPublisher(
        service_factory=lambda: cast(SheetsServiceProtocol, service)
    )

    publisher.publish(_request("cp-2026", "03", (("header", "hours"), ("first", 1.0))))
    publisher.publish(_request("cp-2026", "03", (("header", "hours"), ("second", 2.5))))

    assert service.worksheet_rows("cp-2026", "03") == (
        ("header", "hours"),
        ("second", 2.5),
    )


def test_resolver_creates_missing_year_and_publisher_uses_new_spreadsheet() -> None:
    """Scenario
    Given a resolver without a spreadsheet ID for the requested year
    When the year is resolved and a monthly worksheet is published
    Then a new spreadsheet is created and receives the uploaded worksheet rows.
    """

    service = StatefulFakeSheetsService()
    resolver = GoogleSheetsResolver(
        spreadsheet_ids={},
        title_prefix="Jira Worklog Analytics - Click Price",
        service_factory=lambda: cast(SheetsServiceProtocol, service),
    )
    publisher = GoogleSheetsPublisher(
        service_factory=lambda: cast(SheetsServiceProtocol, service)
    )

    target = resolver.resolve(2025)
    publisher.publish(
        SpreadsheetPublishRequest(
            year=2025,
            spreadsheet_id=target.spreadsheet_id,
            worksheets=(
                WorksheetData(
                    "01",
                    (
                        ("issue_key", "issue_type", "hours"),
                        ("LA004832-1", "Bug", 1.0),
                    ),
                ),
            ),
        )
    )

    assert target.spreadsheet_id in service.spreadsheets_state
    assert service.worksheet_rows(target.spreadsheet_id, "01") == (
        ("issue_key", "issue_type", "hours"),
        ("LA004832-1", "Bug", 1.0),
    )


def _request(
    spreadsheet_id: str,
    worksheet_title: str,
    rows: tuple[tuple[SheetCellValue, ...], ...],
) -> SpreadsheetPublishRequest:
    return SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id=spreadsheet_id,
        worksheets=(WorksheetData(worksheet_title, rows),),
    )
