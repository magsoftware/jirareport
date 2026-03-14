from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeSheetsRequest:
    """Represents one completed fake Google Sheets API request."""

    response: dict[str, object] = field(default_factory=dict)

    def execute(self) -> dict[str, object]:
        """Returns the configured response payload."""
        return self.response


@dataclass
class FakeSpreadsheetState:
    """Stores worksheet rows and metadata for one fake spreadsheet."""

    title: str
    locale: str = "en_US"
    worksheets: dict[str, tuple[tuple[object, ...], ...]] = field(default_factory=dict)
    sheet_ids: dict[str, int] = field(default_factory=dict)
    batch_updates: list[dict[str, object]] = field(default_factory=list)


class FakeSheetsValuesResource:
    """Implements the subset of spreadsheet values operations used in tests."""

    def __init__(self, service: StatefulFakeSheetsService) -> None:
        self._service = service

    def clear(
        self,
        *,
        spreadsheetId: str,
        range: str,
        body: dict[str, object],
    ) -> FakeSheetsRequest:
        del body
        worksheet_title = _worksheet_title(range)
        spreadsheet = self._service.spreadsheets_state[spreadsheetId]
        spreadsheet.worksheets[worksheet_title] = ()
        return FakeSheetsRequest()

    def update(
        self,
        *,
        spreadsheetId: str,
        range: str,
        valueInputOption: str,
        body: dict[str, object],
    ) -> FakeSheetsRequest:
        del valueInputOption
        values = body["values"]
        assert isinstance(values, list)
        worksheet_title = _worksheet_title(range)
        spreadsheet = self._service.spreadsheets_state[spreadsheetId]
        spreadsheet.worksheets[worksheet_title] = tuple(
            tuple(row)
            for row in values
        )
        return FakeSheetsRequest()


class FakeSpreadsheetsResource:
    """Implements the subset of spreadsheet operations used by the adapter."""

    def __init__(self, service: StatefulFakeSheetsService) -> None:
        self._service = service
        self._values = FakeSheetsValuesResource(service)

    def batchUpdate(
        self,
        *,
        spreadsheetId: str,
        body: dict[str, object],
    ) -> FakeSheetsRequest:
        spreadsheet = self._service.spreadsheets_state[spreadsheetId]
        spreadsheet.batch_updates.append(body)
        requests = body["requests"]
        assert isinstance(requests, list)
        for request in requests:
            add_sheet = request.get("addSheet")
            if not isinstance(add_sheet, dict):
                continue
            properties = add_sheet["properties"]
            assert isinstance(properties, dict)
            title = properties["title"]
            assert isinstance(title, str)
            if title not in spreadsheet.sheet_ids:
                spreadsheet.sheet_ids[title] = len(spreadsheet.sheet_ids) + 1
                spreadsheet.worksheets.setdefault(title, ())
        return FakeSheetsRequest()

    def create(
        self,
        *,
        body: dict[str, object],
        fields: str,
    ) -> FakeSheetsRequest:
        assert fields == "spreadsheetId,spreadsheetUrl"
        properties = body["properties"]
        assert isinstance(properties, dict)
        title = properties["title"]
        assert isinstance(title, str)
        spreadsheet_id = f"created-{len(self._service.spreadsheets_state) + 1}"
        self._service.spreadsheets_state[spreadsheet_id] = FakeSpreadsheetState(title=title)
        return FakeSheetsRequest(
            {
                "spreadsheetId": spreadsheet_id,
                "spreadsheetUrl": f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit",
            }
        )

    def get(self, *, spreadsheetId: str, fields: str) -> FakeSheetsRequest:
        assert fields == "properties.locale,sheets.properties(title,sheetId)"
        spreadsheet = self._service.spreadsheets_state[spreadsheetId]
        return FakeSheetsRequest(
            {
                "properties": {"locale": spreadsheet.locale},
                "sheets": [
                    {"properties": {"title": title, "sheetId": sheet_id}}
                    for title, sheet_id in spreadsheet.sheet_ids.items()
                ],
            }
        )

    def values(self) -> FakeSheetsValuesResource:
        """Returns the fake values resource."""
        return self._values


class StatefulFakeSheetsService:
    """In-memory Google Sheets service that stores worksheet state."""

    def __init__(self) -> None:
        self.spreadsheets_state: dict[str, FakeSpreadsheetState] = {}
        self._spreadsheets = FakeSpreadsheetsResource(self)

    def spreadsheets(self) -> FakeSpreadsheetsResource:
        """Returns the fake spreadsheets resource."""
        return self._spreadsheets

    def add_spreadsheet(
        self,
        spreadsheet_id: str,
        *,
        title: str,
        locale: str = "en_US",
        worksheet_titles: tuple[str, ...] = (),
    ) -> None:
        """Creates an initial spreadsheet state used by tests."""
        self.spreadsheets_state[spreadsheet_id] = FakeSpreadsheetState(
            title=title,
            locale=locale,
            worksheets={worksheet_title: () for worksheet_title in worksheet_titles},
            sheet_ids={
                worksheet_title: index + 1
                for index, worksheet_title in enumerate(worksheet_titles)
            },
        )

    def worksheet_rows(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
    ) -> tuple[tuple[object, ...], ...]:
        """Returns the stored rows for one worksheet."""
        return self.spreadsheets_state[spreadsheet_id].worksheets[worksheet_title]


def _worksheet_title(value_range: str) -> str:
    """Extracts the worksheet title from an A1 range or bare worksheet name."""
    return value_range.split("!", maxsplit=1)[0]
