from __future__ import annotations

from typing import Any

from jirareport.domain.models import SpreadsheetPublishRequest, WorksheetData
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
)


class FakeRequest:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {}

    def execute(self) -> dict[str, Any]:
        return self.response


class FakeValuesApi:
    def __init__(self) -> None:
        self.cleared: list[tuple[str, str]] = []
        self.updated: list[tuple[str, str, list[list[object]]]] = []

    def clear(
        self,
        *,
        spreadsheetId: str,
        range: str,
        body: dict[str, object],
    ) -> FakeRequest:
        self.cleared.append((spreadsheetId, range))
        return FakeRequest()

    def update(
        self,
        *,
        spreadsheetId: str,
        range: str,
        valueInputOption: str,
        body: dict[str, object],
    ) -> FakeRequest:
        values = body["values"]
        assert isinstance(values, list)
        self.updated.append((spreadsheetId, range, values))
        return FakeRequest()


class FakeSpreadsheetsApi:
    def __init__(self, titles: list[str], locale: str = "en_US") -> None:
        self.values_api = FakeValuesApi()
        self.created_tabs: list[str] = []
        self.batch_updates: list[dict[str, object]] = []
        self.created_spreadsheets: list[str] = []
        self.sheet_ids = {title: index + 1 for index, title in enumerate(titles)}
        self.locale = locale

    def get(self, *, spreadsheetId: str, fields: str) -> FakeRequest:
        assert fields == "properties.locale,sheets.properties(title,sheetId)"
        response = {
            "properties": {"locale": self.locale},
            "sheets": [
                {"properties": {"title": title, "sheetId": sheet_id}}
                for title, sheet_id in self.sheet_ids.items()
            ]
        }
        return FakeRequest(response)

    def batchUpdate(
        self,
        *,
        spreadsheetId: str,
        body: dict[str, object],
    ) -> FakeRequest:
        requests = body["requests"]
        assert isinstance(requests, list)
        self.batch_updates.append(body)
        for item in requests:
            add_sheet = item.get("addSheet")
            if add_sheet is None:
                continue
            title = add_sheet["properties"]["title"]
            self.created_tabs.append(title)
            self.sheet_ids[title] = len(self.sheet_ids) + 1
        return FakeRequest()

    def create(self, *, body: dict[str, object], fields: str) -> FakeRequest:
        properties = body["properties"]
        assert isinstance(properties, dict)
        title = properties["title"]
        assert isinstance(title, str)
        self.created_spreadsheets.append(title)
        spreadsheet_id = f"created-{title.split()[-1]}"
        return FakeRequest(
            {
                "spreadsheetId": spreadsheet_id,
                "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            }
        )

    def values(self) -> FakeValuesApi:
        return self.values_api


class FakeSheetsService:
    def __init__(self, titles: list[str], locale: str = "en_US") -> None:
        self.spreadsheets_api = FakeSpreadsheetsApi(titles, locale=locale)

    def spreadsheets(self) -> FakeSpreadsheetsApi:
        return self.spreadsheets_api


def test_google_sheets_publisher_creates_missing_tabs_rewrites_values_and_formats(
) -> None:
    service = FakeSheetsService(["raw_worklogs"], locale="en_US")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData("raw_worklogs", (("h1", "h2"), ("a", 1))),
            WorksheetData(
                "monthly_summary",
                (
                    ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"),
                    ("2026-03", "PRJ-1", "Summary", "Alice", "alice-1", 2, 3600, 1.0),
                    (
                        "VISIBLE_TOTALS",
                        "",
                        "",
                        "",
                        "",
                        "=SUBTOTAL(109,F2:F2)",
                        "=SUBTOTAL(109,G2:G2)",
                        "=SUBTOTAL(109,H2:H2)",
                    ),
                ),
            ),
        ),
    )

    result = publisher.publish(request)

    assert service.spreadsheets_api.created_tabs == ["monthly_summary"]
    assert service.spreadsheets_api.values_api.cleared == [
        ("sheet-2026", "raw_worklogs"),
        ("sheet-2026", "monthly_summary"),
    ]
    assert service.spreadsheets_api.values_api.updated == [
        ("sheet-2026", "raw_worklogs!A1", [["h1", "h2"], ["a", 1]]),
        (
            "sheet-2026",
            "monthly_summary!A1",
            [
                ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"],
                ["2026-03", "PRJ-1", "Summary", "Alice", "alice-1", 2, 3600, 1.0],
                [
                    "VISIBLE_TOTALS",
                    "",
                    "",
                    "",
                    "",
                    "=SUBTOTAL(109,F2:F2)",
                    "=SUBTOTAL(109,G2:G2)",
                    "=SUBTOTAL(109,H2:H2)",
                ],
            ],
        ),
    ]
    formatting_requests = service.spreadsheets_api.batch_updates[-1]["requests"]
    assert isinstance(formatting_requests, list)
    assert any("setBasicFilter" in request_item for request_item in formatting_requests)
    assert result == "https://docs.google.com/spreadsheets/d/sheet-2026/edit"


def test_google_sheets_resolver_creates_missing_yearly_spreadsheet() -> None:
    service = FakeSheetsService([])
    resolver = GoogleSheetsResolver(
        spreadsheet_ids={2026: "sheet-2026"},
        title_prefix="Jira Worklog Analytics",
        service_factory=lambda: service,
    )

    target = resolver.resolve(2027)

    assert service.spreadsheets_api.created_spreadsheets == [
        "Jira Worklog Analytics 2027"
    ]
    assert target.year == 2027
    assert target.spreadsheet_id == "created-2027"
    assert (
        target.spreadsheet_url
        == "https://docs.google.com/spreadsheets/d/created-2027/edit"
    )


def test_google_sheets_publisher_localizes_formulas_for_polish_locale() -> None:
    service = FakeSheetsService(["monthly_summary"], locale="pl_PL")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData(
                "monthly_summary",
                (
                    ("month", "total_hours"),
                    ("2026-03", 1.5),
                    ("VISIBLE_TOTALS", "=SUBTOTAL(109,H2:H2)"),
                ),
            ),
        ),
    )

    publisher.publish(request)

    assert service.spreadsheets_api.values_api.updated == [
        (
            "sheet-2026",
            "monthly_summary!A1",
            [
                ["month", "total_hours"],
                ["2026-03", 1.5],
                ["VISIBLE_TOTALS", "=SUBTOTAL(109;H2:H2)"],
            ],
        ),
    ]


def test_google_sheets_resolver_reuses_existing_spreadsheet_id() -> None:
    resolver = GoogleSheetsResolver(
        spreadsheet_ids={2026: "sheet-2026"},
        title_prefix="Jira Worklog Analytics",
    )

    target = resolver.resolve(2026)

    assert target.spreadsheet_id == "sheet-2026"
    assert target.spreadsheet_url == "https://docs.google.com/spreadsheets/d/sheet-2026/edit"


def test_google_sheets_publisher_skips_filter_for_metadata_and_empty_number_formats(
) -> None:
    service = FakeSheetsService(["metadata"], locale="en_US")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(WorksheetData("metadata", (("h1", "h2"),)),),
    )

    publisher.publish(request)

    formatting_requests = service.spreadsheets_api.batch_updates[-1]["requests"]
    assert isinstance(formatting_requests, list)
    assert not any(
        "setBasicFilter" in request_item for request_item in formatting_requests
    )


def test_google_sheets_publisher_formats_daily_summary_columns() -> None:
    service = FakeSheetsService(["daily_summary"], locale="en_US")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData(
                "daily_summary",
                (
                    (
                        "date",
                        "month",
                        "issue",
                        "summary",
                        "author",
                        "account",
                        "entries",
                        "seconds",
                        "hours",
                    ),
                    (
                        "2026-03-11",
                        "2026-03",
                        "PRJ-1",
                        "Summary",
                        "Alice",
                        "alice-1",
                        2,
                        3600,
                        1.0,
                    ),
                    (
                        "VISIBLE_TOTALS",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "=SUBTOTAL(109,G2:G2)",
                        "=SUBTOTAL(109,H2:H2)",
                        "=SUBTOTAL(109,I2:I2)",
                    ),
                ),
            ),
        ),
    )

    publisher.publish(request)

    formatting_requests = service.spreadsheets_api.batch_updates[-1]["requests"]
    assert isinstance(formatting_requests, list)
    repeat_cell_requests = [
        request_item["repeatCell"]
        for request_item in formatting_requests
        if "repeatCell" in request_item
    ]
    assert any(
        item["cell"]["userEnteredFormat"]
        .get("numberFormat", {})
        .get("pattern")
        == "0.00"
        for item in repeat_cell_requests
    )
