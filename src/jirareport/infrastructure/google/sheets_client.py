from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger

from jirareport.domain.models import (
    SpreadsheetPublishRequest,
    SpreadsheetTarget,
    WorksheetData,
)

SheetsServiceFactory = Callable[[], Any]
HEADER_COLOR = {"red": 0.87, "green": 0.92, "blue": 0.98}
TOTALS_COLOR = {"red": 0.95, "green": 0.95, "blue": 0.95}
SUMMARY_TABS = {"monthly_summary", "daily_summary"}


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
        service: Any,
        request: SpreadsheetPublishRequest,
    ) -> tuple[dict[str, int], str]:
        """Creates missing tabs before uploading their contents."""
        titles, locale = _spreadsheet_metadata(service, request.spreadsheet_id)
        missing = [
            sheet.title
            for sheet in request.worksheets
            if sheet.title not in titles
        ]
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
        response = service.spreadsheets().create(
            body={"properties": {"title": f"{self._title_prefix} {year}"}},
            fields="spreadsheetId,spreadsheetUrl",
        ).execute()
        spreadsheet_id = response["spreadsheetId"]
        spreadsheet_url = response["spreadsheetUrl"]
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
    service: Any,
    spreadsheet_id: str,
) -> tuple[dict[str, int], str]:
    """Loads worksheet metadata and locale for a spreadsheet."""
    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="properties.locale,sheets.properties(title,sheetId)",
    ).execute()
    sheets = response.get("sheets", [])
    return (
        {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in sheets
        },
        response["properties"]["locale"],
    )


def _add_sheet_request(title: str) -> dict[str, dict[str, dict[str, str]]]:
    """Builds a request body for creating one missing sheet tab."""
    return {"addSheet": {"properties": {"title": title}}}


def _write_worksheet(
    service: Any,
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


def _worksheet_values(worksheet: WorksheetData, locale: str) -> list[list[Any]]:
    """Converts immutable worksheet rows to the API payload format."""
    return [
        [_localized_formula(cell, locale) for cell in row]
        for row in worksheet.rows
    ]


def _localized_formula(value: Any, locale: str) -> Any:
    """Localizes known formulas to the destination spreadsheet locale."""
    if not isinstance(value, str) or not value.startswith("="):
        return value
    if locale.startswith("pl_"):
        return value.replace(",", ";")
    return value


def _format_worksheet(
    service: Any,
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
    if worksheet.title in SUMMARY_TABS and row_count > 1:
        requests.append(_totals_row_format_request(sheet_id, row_count, column_count))
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


def _totals_row_format_request(
    sheet_id: int,
    row_count: int,
    column_count: int,
) -> dict[str, object]:
    """Builds a request that formats the summary totals row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_count - 1,
                "endRowIndex": row_count,
                "startColumnIndex": 0,
                "endColumnIndex": column_count,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": TOTALS_COLOR,
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
    if worksheet.title == "metadata":
        return None
    row_count = len(worksheet.rows)
    if worksheet.title in SUMMARY_TABS:
        row_count -= 1
    return {
        "setBasicFilter": {
            "filter": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": row_count,
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
    if worksheet.title == "raw_worklogs":
        requests.append(_column_number_format_request(sheet_id, 16, 17, "NUMBER", "0"))
        requests.append(
            _column_number_format_request(sheet_id, 17, 18, "NUMBER", "0.00")
        )
    if worksheet.title == "monthly_summary":
        requests.append(
            _column_number_format_request(
                sheet_id,
                5,
                6,
                "NUMBER",
                "0",
            )
        )
        requests.append(
            _column_number_format_request(
                sheet_id,
                6,
                7,
                "NUMBER",
                "0",
            )
        )
        requests.append(
            _column_number_format_request(
                sheet_id,
                7,
                8,
                "NUMBER",
                "0.00",
            )
        )
        requests.extend(
            _summary_footer_number_formats(
                sheet_id,
                row_count,
                entries_column_index=5,
                seconds_column_index=6,
                hours_column_index=7,
            )
        )
    if worksheet.title == "daily_summary":
        requests.append(
            _column_number_format_request(
                sheet_id,
                6,
                7,
                "NUMBER",
                "0",
            )
        )
        requests.append(
            _column_number_format_request(
                sheet_id,
                7,
                8,
                "NUMBER",
                "0",
            )
        )
        requests.append(
            _column_number_format_request(
                sheet_id,
                8,
                9,
                "NUMBER",
                "0.00",
            )
        )
        requests.extend(
            _summary_footer_number_formats(
                sheet_id,
                row_count,
                entries_column_index=6,
                seconds_column_index=7,
                hours_column_index=8,
            )
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
        "endRowIndex": 99999,
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


def _summary_footer_number_formats(
    sheet_id: int,
    row_count: int,
    entries_column_index: int,
    seconds_column_index: int,
    hours_column_index: int,
) -> list[dict[str, object]]:
    """Builds explicit number formats for the visible totals footer row."""
    footer_start = row_count - 1
    return [
        _footer_number_format_request(
            sheet_id,
            footer_start,
            entries_column_index,
            "0",
        ),
        _footer_number_format_request(
            sheet_id,
            footer_start,
            seconds_column_index,
            "0",
        ),
        _footer_number_format_request(
            sheet_id,
            footer_start,
            hours_column_index,
            "0.00",
        ),
    ]


def _footer_number_format_request(
    sheet_id: int,
    row_index: int,
    column_index: int,
    pattern: str,
) -> dict[str, object]:
    """Builds a number-format request for one totals cell."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_index,
                "endRowIndex": row_index + 1,
                "startColumnIndex": column_index,
                "endColumnIndex": column_index + 1,
            },
            "cell": {
                "userEnteredFormat": {
                    "numberFormat": {
                        "type": "NUMBER",
                        "pattern": pattern,
                    }
                }
            },
            "fields": "userEnteredFormat.numberFormat",
        }
    }


def _spreadsheet_url(spreadsheet_id: str) -> str:
    """Builds the browser URL for a Google spreadsheet."""
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _default_sheets_service_factory() -> Any:
    """Builds the default authenticated Google Sheets service client."""
    from googleapiclient.discovery import build

    return build("sheets", "v4", cache_discovery=False)
