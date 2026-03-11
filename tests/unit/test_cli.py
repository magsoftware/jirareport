from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from jirareport.domain.models import MonthId
from jirareport.infrastructure.config import (
    AppSettings,
    JiraSettings,
    SheetsSettings,
    StorageSettings,
)
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.interfaces.cli import app


@dataclass(frozen=True)
class DailyResult:
    snapshot_path: str


@dataclass(frozen=True)
class MonthlyResult:
    report_path: str


@dataclass(frozen=True)
class SyncSheetsResult:
    spreadsheet_urls: tuple[str, ...]


@dataclass
class FakeDailyService:
    source: object
    storage: object
    project_key: str
    timezone_name: str

    last_date: date | None = None

    def generate(self, reference_date: date) -> DailyResult:
        self.last_date = reference_date
        return DailyResult(snapshot_path="raw/daily.json")


@dataclass
class FakeMonthlyService:
    source: object
    storage: object
    project_key: str
    timezone_name: str

    last_month: MonthId | None = None

    def generate(self, month: MonthId) -> MonthlyResult:
        self.last_month = month
        return MonthlyResult(report_path="derived/monthly.json")


@dataclass
class FakeSheetsSyncService:
    source: object
    publisher: object
    project_key: str
    spreadsheet_ids: dict[int, str]
    timezone_name: str

    last_date: date | None = None

    def generate(self, reference_date: date) -> SyncSheetsResult:
        self.last_date = reference_date
        return SyncSheetsResult(
            spreadsheet_urls=("https://docs.google.com/spreadsheets/d/sheet/edit",)
        )


def test_main_dispatches_daily_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    fake_daily = FakeDailyService(None, None, "PRJ", "Europe/Warsaw")
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings: object())
    monkeypatch.setattr(app, "build_storage", lambda *args: object())
    monkeypatch.setattr(app, "DailySnapshotService", lambda *args, **kwargs: fake_daily)

    result = app.main(["daily", "--date", "2026-03-11"])

    assert result == 0
    assert str(fake_daily.last_date) == "2026-03-11"


def test_main_dispatches_monthly_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    fake_monthly = FakeMonthlyService(None, None, "PRJ", "Europe/Warsaw")
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings: object())
    monkeypatch.setattr(app, "build_storage", lambda *args: object())
    monkeypatch.setattr(
        app,
        "MonthlyReportService",
        lambda *args, **kwargs: fake_monthly,
    )

    result = app.main(["monthly", "--month", "2026-03"])

    assert result == 0
    assert fake_monthly.last_month is not None
    assert fake_monthly.last_month.label() == "2026-03"


def test_main_dispatches_sync_sheets_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    fake_sync = FakeSheetsSyncService(
        None,
        None,
        "PRJ",
        {2026: "sheet"},
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings: object())
    monkeypatch.setattr(app, "_build_spreadsheet_publisher", lambda settings: object())
    monkeypatch.setattr(
        app,
        "_build_spreadsheet_resolver",
        lambda settings: object(),
    )
    monkeypatch.setattr(
        app,
        "SheetsSyncService",
        lambda *args, **kwargs: fake_sync,
    )

    result = app.main(["sync", "sheets", "--date", "2026-03-11"])

    assert result == 0
    assert str(fake_sync.last_date) == "2026-03-11"


def test_build_source_uses_jira_settings() -> None:
    source = app._build_source(_settings())

    jira_source = cast(JiraWorklogSource, source)
    assert jira_source._project_key == "PRJ"


def _settings() -> AppSettings:
    return AppSettings(
        jira=JiraSettings(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="secret",
            project_key="PRJ",
        ),
        storage=StorageSettings(
            backend="local",
            local_output_dir=Path("reports"),
            bucket_name=None,
            bucket_prefix="jirareport",
        ),
        sheets=SheetsSettings(
            enabled=True,
            spreadsheet_ids={2026: "sheet-2026"},
            title_prefix="Jira Worklog Analytics",
        ),
        timezone_name="Europe/Warsaw",
    )
