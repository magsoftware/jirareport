from __future__ import annotations

from typing import Any

from jirareport.domain.models import SpreadsheetPublishRequest, WorksheetData
from jirareport.infrastructure.google.sheets_client import GoogleSheetsPublisher


class FakeRequest:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {}

    def execute(self) -> dict[str, object]:
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
    def __init__(self, titles: list[str]) -> None:
        self._titles = titles
        self.values_api = FakeValuesApi()
        self.created_tabs: list[str] = []

    def get(self, *, spreadsheetId: str, fields: str) -> FakeRequest:
        assert fields == "sheets.properties.title"
        response = {
            "sheets": [{"properties": {"title": title}} for title in self._titles]
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
        for item in requests:
            add_sheet = item["addSheet"]
            self.created_tabs.append(add_sheet["properties"]["title"])
        return FakeRequest()

    def values(self) -> FakeValuesApi:
        return self.values_api


class FakeSheetsService:
    def __init__(self, titles: list[str]) -> None:
        self.spreadsheets_api = FakeSpreadsheetsApi(titles)

    def spreadsheets(self) -> FakeSpreadsheetsApi:
        return self.spreadsheets_api


def test_google_sheets_publisher_creates_missing_tabs_and_rewrites_values() -> None:
    service = FakeSheetsService(["raw_worklogs"])
    publisher = GoogleSheetsPublisher(service_factory=lambda: service)
    request = SpreadsheetPublishRequest(
        year=2026,
        spreadsheet_id="sheet-2026",
        worksheets=(
            WorksheetData("raw_worklogs", (("h1", "h2"), ("a", 1))),
            WorksheetData("monthly_summary", (("m1",),)),
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
        ("sheet-2026", "monthly_summary!A1", [["m1"]]),
    ]
    assert result == "https://docs.google.com/spreadsheets/d/sheet-2026/edit"
