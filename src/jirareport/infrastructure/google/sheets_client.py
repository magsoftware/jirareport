from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger

from jirareport.domain.models import SpreadsheetPublishRequest, WorksheetData

SheetsServiceFactory = Callable[[], Any]


class GoogleSheetsPublisher:
    """Publishes yearly report tabs to Google Sheets."""

    def __init__(self, service_factory: SheetsServiceFactory | None = None) -> None:
        """Initializes the publisher with a Sheets API service factory."""
        self._service_factory = service_factory or _default_sheets_service_factory

    def publish(self, request: SpreadsheetPublishRequest) -> str:
        """Publishes all managed tabs to the configured yearly spreadsheet."""
        service = self._service_factory()
        self._ensure_worksheets(service, request)
        for worksheet in request.worksheets:
            _write_worksheet(service, request.spreadsheet_id, worksheet)
            logger.info(
                "Published {} row(s) to spreadsheet {} tab {}.",
                len(worksheet.rows) - 1,
                request.year,
                worksheet.title,
            )
        return _spreadsheet_url(request.spreadsheet_id)

    def _ensure_worksheets(
        self,
        service: Any,
        request: SpreadsheetPublishRequest,
    ) -> None:
        """Creates missing tabs before uploading their contents."""
        titles = _worksheet_titles(service, request.spreadsheet_id)
        missing = [
            sheet.title
            for sheet in request.worksheets
            if sheet.title not in titles
        ]
        if not missing:
            return
        body = {"requests": [_add_sheet_request(title) for title in missing]}
        service.spreadsheets().batchUpdate(
            spreadsheetId=request.spreadsheet_id,
            body=body,
        ).execute()


def _worksheet_titles(service: Any, spreadsheet_id: str) -> set[str]:
    """Loads existing tab titles for a spreadsheet."""
    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title",
    ).execute()
    sheets = response.get("sheets", [])
    return {sheet["properties"]["title"] for sheet in sheets}


def _add_sheet_request(title: str) -> dict[str, dict[str, dict[str, str]]]:
    """Builds a request body for creating one missing sheet tab."""
    return {"addSheet": {"properties": {"title": title}}}


def _write_worksheet(
    service: Any,
    spreadsheet_id: str,
    worksheet: WorksheetData,
) -> None:
    """Clears and rewrites one worksheet from the header row downward."""
    values = _worksheet_values(worksheet)
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=worksheet.title,
        body={},
    ).execute()
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{worksheet.title}!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def _worksheet_values(worksheet: WorksheetData) -> list[list[Any]]:
    """Converts immutable worksheet rows to the API payload format."""
    return [list(row) for row in worksheet.rows]


def _spreadsheet_url(spreadsheet_id: str) -> str:
    """Builds the browser URL for a Google spreadsheet."""
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def _default_sheets_service_factory() -> Any:
    """Builds the default authenticated Google Sheets service client."""
    from googleapiclient.discovery import build

    return build("sheets", "v4", cache_discovery=False)
