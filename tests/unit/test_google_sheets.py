from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from jirareport.domain.models import SpreadsheetPublishRequest, WorksheetData
from jirareport.infrastructure.google.sheets_client import (
    GoogleSheetsPublisher,
    GoogleSheetsResolver,
    _basic_filter_request,
    _localized_formula,
    _number_format_requests,
)


class FakeRequest:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {}

    def execute(self) -> Mapping[str, object]:
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
        body: Mapping[str, object],
    ) -> FakeRequest:
        self.cleared.append((spreadsheetId, range))
        return FakeRequest()

    def update(
        self,
        *,
        spreadsheetId: str,
        range: str,
        valueInputOption: str,
        body: Mapping[str, object],
    ) -> FakeRequest:
        values = body["values"]
        assert isinstance(values, list)
        self.updated.append((spreadsheetId, range, values))
        return FakeRequest()


class FakeSpreadsheetsApi:
    def __init__(self, titles: list[str], locale: str = "en_US") -> None:
        self.values_api = FakeValuesApi()
        self.created_tabs: list[str] = []
        self.batch_updates: list[Mapping[str, object]] = []
        self.created_spreadsheets: list[str] = []
        self.sheet_ids = {title: index + 1 for index, title in enumerate(titles)}
        self.locale = locale

    def get(self, *, spreadsheetId: str, fields: str) -> FakeRequest:
        assert fields == "properties.locale,sheets.properties(title,sheetId)"
        response = {
            "properties": {"locale": self.locale},
            "sheets": [
                {"properties": {"title": title, "sheetId": sheet_id}} for title, sheet_id in self.sheet_ids.items()
            ],
        }
        return FakeRequest(response)

    def batchUpdate(
        self,
        *,
        spreadsheetId: str,
        body: Mapping[str, object],
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

    def create(self, *, body: Mapping[str, object], fields: str) -> FakeRequest:
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


def test_google_sheets_publisher_creates_missing_month_tabs_and_formats_raw_columns() -> None:
    service = FakeSheetsService(["02"], locale="en_US")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData(
                "02",
                (
                    (
                        "snapshot_date",
                        "window_start",
                        "window_end",
                        "generated_at",
                        "timezone",
                        "month",
                        "issue_key",
                        "summary",
                        "issue_type",
                        "author",
                        "author_account_id",
                        "worklog_id",
                        "started_at",
                        "ended_at",
                        "started_date",
                        "ended_date",
                        "crosses_midnight",
                        "duration_seconds",
                        "duration_hours",
                    ),
                    (
                        "2026-03-12",
                        "2026-02-01",
                        "2026-03-12",
                        "2026-03-12T01:05:00+01:00",
                        "Europe/Warsaw",
                        "2026-02",
                        "PRJ-1",
                        "Summary",
                        "Bug",
                        "Alice",
                        "alice-1",
                        "1",
                        "2026-02-03T09:00:00+01:00",
                        "2026-02-03T10:00:00+01:00",
                        "2026-02-03",
                        "2026-02-03",
                        "FALSE",
                        3600,
                        1.0,
                    ),
                ),
            ),
            WorksheetData("03", (("h1", "h2"),)),
        ),
    )

    result = publisher.publish(request)

    assert service.spreadsheets_api.created_tabs == ["03"]
    assert service.spreadsheets_api.values_api.cleared == [
        ("sheet-2026", "02"),
        ("sheet-2026", "03"),
    ]
    assert service.spreadsheets_api.values_api.updated[0][0:2] == (
        "sheet-2026",
        "02!A1",
    )
    formatting_requests = [
        request_item
        for batch in service.spreadsheets_api.batch_updates
        for request_item in cast(list[dict[str, object]], batch["requests"])
    ]
    repeat_cell_requests = [
        cast(dict[str, Any], request_item["repeatCell"])
        for request_item in formatting_requests
        if "repeatCell" in request_item
    ]
    assert any(
        item["cell"]["userEnteredFormat"].get("numberFormat", {}).get("pattern") == "0.00"
        for item in repeat_cell_requests
    )
    assert any("setBasicFilter" in request_item for request_item in formatting_requests)
    assert result == "https://docs.google.com/spreadsheets/d/sheet-2026/edit"


def test_google_sheets_publisher_localizes_formula_for_polish_locale() -> None:
    service = FakeSheetsService(["03"], locale="pl_PL")
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData(
                "03",
                (
                    ("header", "value"),
                    ("formula", "=SUBTOTAL(109,H2:H2)"),
                ),
            ),
        ),
    )

    publisher.publish(request)

    assert service.spreadsheets_api.values_api.updated == [
        (
            "sheet-2026",
            "03!A1",
            [["header", "value"], ["formula", "=SUBTOTAL(109;H2:H2)"]],
        ),
    ]


def test_google_sheets_resolver_creates_missing_yearly_spreadsheet() -> None:
    service = FakeSheetsService([])
    resolver = GoogleSheetsResolver(
        spreadsheet_ids={2026: "sheet-2026"},
        title_prefix="Jira Worklog Analytics",
        service_factory=lambda: service,
    )

    target = resolver.resolve(2027)

    assert service.spreadsheets_api.created_spreadsheets == ["Jira Worklog Analytics 2027"]
    assert target.year == 2027
    assert target.spreadsheet_id == "created-2027"
    assert target.spreadsheet_url == "https://docs.google.com/spreadsheets/d/created-2027/edit"


def test_google_sheets_resolver_reuses_existing_spreadsheet_id() -> None:
    resolver = GoogleSheetsResolver(
        spreadsheet_ids={2026: "sheet-2026"},
        title_prefix="Jira Worklog Analytics",
    )

    target = resolver.resolve(2026)

    assert target.spreadsheet_id == "sheet-2026"
    assert target.spreadsheet_url == "https://docs.google.com/spreadsheets/d/sheet-2026/edit"


def test_localized_formula_keeps_non_formula_values_unchanged() -> None:
    assert _localized_formula("plain text", "pl_PL") == "plain text"
    assert _localized_formula(123, "pl_PL") == 123
    assert _localized_formula("=SUM(A1,B1)", "en_US") == "=SUM(A1,B1)"


def test_basic_filter_request_returns_none_for_empty_worksheet() -> None:
    assert _basic_filter_request(1, WorksheetData("01", ())) is None


def test_number_format_requests_skip_short_or_non_monthly_worksheets() -> None:
    assert _number_format_requests(1, WorksheetData("01", (("header",),))) == []
    assert (
        _number_format_requests(
            1,
            WorksheetData("raw", (("header", "value"), ("a", 1))),
        )
        == []
    )
