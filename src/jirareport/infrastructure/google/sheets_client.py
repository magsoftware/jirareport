from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol, cast

from loguru import logger

from jirareport.domain.models import (
    SheetCellValue,
    SpreadsheetPublishRequest,
    SpreadsheetTarget,
    WorksheetData,
)


class SheetsRequestProtocol(Protocol):
    """Describes the subset of request behavior used by the adapter."""

    def execute(self) -> Mapping[str, object]:
        """Executes one Google Sheets API request."""


class SheetsValuesResourceProtocol(Protocol):
    """Describes the subset of values resource behavior used by the adapter."""

    def clear(
        self,
        *,
        spreadsheetId: str,
        range: str,
        body: Mapping[str, object],
    ) -> SheetsRequestProtocol:
        """Clears worksheet values in the requested range."""

    def update(
        self,
        *,
        spreadsheetId: str,
        range: str,
        valueInputOption: str,
        body: Mapping[str, object],
    ) -> SheetsRequestProtocol:
        """Updates worksheet values starting from the requested cell."""


class SpreadsheetsResourceProtocol(Protocol):
    """Describes the subset of spreadsheets resource behavior used here."""

    def batchUpdate(
        self,
        *,
        spreadsheetId: str,
        body: Mapping[str, object],
    ) -> SheetsRequestProtocol:
        """Applies a batch of spreadsheet changes."""

    def create(
        self,
        *,
        body: Mapping[str, object],
        fields: str,
    ) -> SheetsRequestProtocol:
        """Creates one spreadsheet and returns selected fields."""

    def get(
        self,
        *,
        spreadsheetId: str,
        fields: str,
    ) -> SheetsRequestProtocol:
        """Loads spreadsheet metadata."""

    def values(self) -> SheetsValuesResourceProtocol:
        """Returns the values resource."""


class SheetsServiceProtocol(Protocol):
    """Describes the subset of the Sheets API client used by the adapter."""

    def spreadsheets(self) -> SpreadsheetsResourceProtocol:
        """Returns the spreadsheets resource."""


SheetsServiceFactory = Callable[[], SheetsServiceProtocol]
HEADER_COLOR = {"red": 0.87, "green": 0.92, "blue": 0.98}
# Column indices within the monthly raw worksheet (0-based).
_COL_DURATION_SECONDS = 16
_COL_DURATION_HOURS = 17
# Sentinel used to extend number-format requests through all data rows.
_MAX_DATA_ROWS = 100_000


class GoogleSheetsPublisher:
    """Publishes yearly report tabs to Google Sheets."""

    def __init__(self, service_factory: SheetsServiceFactory | None = None) -> None:
        """Initializes the publisher with a Sheets API service factory."""
        self._service_factory = service_factory or _default_sheets_service_factory

    def publish(self, request: SpreadsheetPublishRequest) -> str:
        """Publishes all managed tabs to the configured yearly spreadsheet."""
        service = self._service_factory()
        logger.info(
            "Starting publish to spreadsheet {} for year {}.",
            request.spreadsheet_id,
            request.year,
        )
        sheet_ids, locale = self._ensure_worksheets(service, request)
        for worksheet in request.worksheets:
            _write_worksheet(service, request.spreadsheet_id, worksheet, locale)
            _format_worksheet(
                service,
                request.spreadsheet_id,
                sheet_ids[worksheet.title],
                worksheet,
            )
            logger.info(
                "Published {} row(s) to spreadsheet {} year {} tab {}.",
                len(worksheet.rows) - 1,
                request.spreadsheet_id,
                request.year,
                worksheet.title,
            )
        logger.info(
            "Completed publish to spreadsheet {} for year {}.",
            request.spreadsheet_id,
            request.year,
        )
        return _spreadsheet_url(request.spreadsheet_id)

    def _ensure_worksheets(
        self,
        service: SheetsServiceProtocol,
        request: SpreadsheetPublishRequest,
    ) -> tuple[dict[str, int], str]:
        """Creates missing tabs before uploading their contents."""
        titles, locale = _spreadsheet_metadata(service, request.spreadsheet_id)
        missing = [sheet.title for sheet in request.worksheets if sheet.title not in titles]
        if missing:
            body = {"requests": [_add_sheet_request(title) for title in missing]}
            service.spreadsheets().batchUpdate(
                spreadsheetId=request.spreadsheet_id,
                body=body,
            ).execute()
            titles, locale = _spreadsheet_metadata(service, request.spreadsheet_id)
        return titles, locale


class GoogleSheetsResolver:
    """Resolves configured yearly spreadsheets and creates missing ones."""

    def __init__(
        self,
        spreadsheet_ids: dict[int, str],
        title_prefix: str,
        service_factory: SheetsServiceFactory | None = None,
    ) -> None:
        """Initializes the resolver with configured IDs and naming rules."""
        self._spreadsheet_ids = spreadsheet_ids
        self._title_prefix = title_prefix
        self._service_factory = service_factory or _default_sheets_service_factory

    def resolve(self, year: int) -> SpreadsheetTarget:
        """Returns or creates the spreadsheet destination for the requested year."""
        spreadsheet_id = self._spreadsheet_ids.get(year)
        if spreadsheet_id is not None:
            return SpreadsheetTarget(
                year=year,
                spreadsheet_id=spreadsheet_id,
                spreadsheet_url=_spreadsheet_url(spreadsheet_id),
            )
        service = self._service_factory()
        response = (
            service.spreadsheets()
            .create(
                body={"properties": {"title": f"{self._title_prefix} {year}"}},
                fields="spreadsheetId,spreadsheetUrl",
            )
            .execute()
        )
        spreadsheet_id = _required_string(response, "spreadsheetId")
        spreadsheet_url = _required_string(response, "spreadsheetUrl")
        self._spreadsheet_ids[year] = spreadsheet_id
        logger.warning(
            "Created spreadsheet for year {}: {}. Persist GOOGLE_SHEETS_ID_{}={}.",
            year,
            spreadsheet_url,
            year,
            spreadsheet_id,
        )
        return SpreadsheetTarget(
            year=year,
            spreadsheet_id=spreadsheet_id,
            spreadsheet_url=spreadsheet_url,
        )


def _spreadsheet_metadata(
    service: SheetsServiceProtocol,
    spreadsheet_id: str,
) -> tuple[dict[str, int], str]:
    """Loads worksheet metadata and locale for a spreadsheet."""
    response = (
        service.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            fields="properties.locale,sheets.properties(title,sheetId)",
        )
        .execute()
    )
    titles: dict[str, int] = {}
    for sheet in _mapping_list(response.get("sheets")):
        properties = _mapping_value(sheet, "properties")
        title = _required_string(properties, "title")
        sheet_id = _required_int(properties, "sheetId")
        titles[title] = sheet_id
    locale = _required_string(_mapping_value(response, "properties"), "locale")
    return titles, locale


def _add_sheet_request(title: str) -> dict[str, dict[str, dict[str, str]]]:
    """Builds a request body for creating one missing sheet tab."""
    return {"addSheet": {"properties": {"title": title}}}


def _write_worksheet(
    service: SheetsServiceProtocol,
    spreadsheet_id: str,
    worksheet: WorksheetData,
    locale: str,
) -> None:
    """Clears and rewrites one worksheet from the header row downward."""
    values = _worksheet_values(worksheet, locale)
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=worksheet.title,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{worksheet.title}!A1",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def _worksheet_values(
    worksheet: WorksheetData,
    locale: str,
) -> list[list[SheetCellValue]]:
    """Converts immutable worksheet rows to the API payload format."""
    return [[_localized_formula(cell, locale) for cell in row] for row in worksheet.rows]


def _localized_formula(value: SheetCellValue, locale: str) -> SheetCellValue:
    """Localizes known formulas to the destination spreadsheet locale."""
    if not isinstance(value, str) or not value.startswith("="):
        return value
    if locale.startswith("pl_"):
        return value.replace(",", ";")
    return value


def _format_worksheet(
    service: SheetsServiceProtocol,
    spreadsheet_id: str,
    sheet_id: int,
    worksheet: WorksheetData,
) -> None:
    """Applies lightweight formatting and filters to one worksheet."""
    column_count = len(worksheet.rows[0]) if worksheet.rows else 0
    row_count = len(worksheet.rows)
    requests = [
        _reset_formatting_request(sheet_id, row_count, column_count),
        _freeze_header_request(sheet_id),
        _header_format_request(sheet_id, column_count),
        _auto_resize_request(sheet_id, column_count),
    ]
    requests.extend(_number_format_requests(sheet_id, worksheet))
    filter_request = _basic_filter_request(sheet_id, worksheet)
    if filter_request is not None:
        requests.append(filter_request)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests},
    ).execute()


def _reset_formatting_request(
    sheet_id: int,
    row_count: int,
    column_count: int,
) -> dict[str, object]:
    """Clears formatting in the populated worksheet area before reapplying styles."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": max(row_count, 1),
                "startColumnIndex": 0,
                "endColumnIndex": column_count,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 1, "green": 1, "blue": 1},
                    "textFormat": {
                        "bold": False,
                        "italic": False,
                        "strikethrough": False,
                        "underline": False,
                    },
                }
            },
            "fields": (
                "userEnteredFormat("
                "backgroundColor,"
                "textFormat.bold,"
                "textFormat.italic,"
                "textFormat.strikethrough,"
                "textFormat.underline"
                ")"
            ),
        }
    }


def _freeze_header_request(sheet_id: int) -> dict[str, object]:
    """Builds a request that freezes the header row."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def _header_format_request(sheet_id: int, column_count: int) -> dict[str, object]:
    """Builds a request that formats the header row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": column_count,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_COLOR,
                    "textFormat": {"bold": True},
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
        }
    }


def _auto_resize_request(sheet_id: int, column_count: int) -> dict[str, object]:
    """Builds a request that auto-resizes all populated columns."""
    return {
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": column_count,
            }
        }
    }


def _basic_filter_request(
    sheet_id: int,
    worksheet: WorksheetData,
) -> dict[str, object] | None:
    """Builds a basic filter request for operational worksheets."""
    if not worksheet.rows:
        return None
    return {
        "setBasicFilter": {
            "filter": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": len(worksheet.rows),
                    "startColumnIndex": 0,
                    "endColumnIndex": len(worksheet.rows[0]),
                }
            }
        }
    }


def _number_format_requests(
    sheet_id: int,
    worksheet: WorksheetData,
) -> list[dict[str, object]]:
    """Builds numeric formatting requests for known worksheet schemas."""
    row_count = len(worksheet.rows)
    if row_count <= 1:
        return []
    requests: list[dict[str, object]] = []
    if _is_monthly_raw_worksheet(worksheet.title):
        requests.append(
            _column_number_format_request(sheet_id, _COL_DURATION_SECONDS, _COL_DURATION_SECONDS + 1, "NUMBER", "0")
        )
        requests.append(
            _column_number_format_request(sheet_id, _COL_DURATION_HOURS, _COL_DURATION_HOURS + 1, "NUMBER", "0.00")
        )
    return requests


def _column_number_format_request(
    sheet_id: int,
    start_column_index: int,
    end_column_index: int,
    number_type: str,
    pattern: str,
) -> dict[str, object]:
    """Builds a number-formatting request for a whole worksheet column range."""
    range_payload = {
        "sheetId": sheet_id,
        "startRowIndex": 1,
        "startColumnIndex": start_column_index,
        "endColumnIndex": end_column_index,
        "endRowIndex": _MAX_DATA_ROWS,
    }
    return {
        "repeatCell": {
            "range": range_payload,
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": number_type,
                        "pattern": pattern,
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def _is_monthly_raw_worksheet(title: str) -> bool:
    """Returns whether the worksheet title matches a monthly raw worksheet."""
    return len(title) == 2 and title.isdigit() and 1 <= int(title) <= 12


def _spreadsheet_url(spreadsheet_id: str) -> str:
    """Builds the browser URL for a Google spreadsheet."""
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _default_sheets_service_factory() -> SheetsServiceProtocol:
    """Builds the default authenticated Google Sheets service client."""
    from googleapiclient.discovery import build

    return cast(SheetsServiceProtocol, build("sheets", "v4", cache_discovery=False))


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    """Returns only mapping items from an arbitrary list payload."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping_value(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Returns a required mapping entry from an API response payload."""
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"Expected mapping field: {key}")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    """Returns a required string entry from an API response payload."""
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected non-empty string field: {key}")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    """Returns a required integer entry from an API response payload."""
    value = payload.get(key)
    if not isinstance(value, int):
        raise ValueError(f"Expected integer field: {key}")
    return value
