from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from jirareport.domain.models import JiraSpace, MonthId
from jirareport.domain.ports import ReportStorage, SpreadsheetPublisher
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
    space: JiraSpace
    timezone_name: str
    last_date: date | None = None

    def generate(self, reference_date: date) -> DailyResult:
        self.last_date = reference_date
        return DailyResult(snapshot_path="raw/daily.json")


@dataclass
class FakeMonthlyService:
    source: object
    storage: object
    space: JiraSpace
    timezone_name: str
    last_month: MonthId | None = None

    def generate(self, month: MonthId) -> MonthlyResult:
        self.last_month = month
        return MonthlyResult(report_path="derived/monthly.json")


@dataclass
class FakeSheetsSyncService:
    source: object
    publisher: object
    resolver: object
    space: JiraSpace
    timezone_name: str
    last_date: date | None = None

    def generate(self, reference_date: date) -> SyncSheetsResult:
        self.last_date = reference_date
        return SyncSheetsResult(
            spreadsheet_urls=("https://docs.google.com/spreadsheets/d/sheet/edit",)
        )


def test_main_dispatches_daily_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_daily = FakeDailyService(None, None, settings.spaces[0], "Europe/Warsaw")
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_storage", lambda settings: object())
    monkeypatch.setattr(app, "DailySnapshotService", lambda *args, **kwargs: fake_daily)

    result = app.main(["daily", "--date", "2026-03-11", "--space", "project"])

    assert result == 0
    assert str(fake_daily.last_date) == "2026-03-11"


def test_main_dispatches_monthly_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_monthly = FakeMonthlyService(None, None, settings.spaces[0], "Europe/Warsaw")
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_storage", lambda settings: object())
    monkeypatch.setattr(
        app,
        "MonthlyReportService",
        lambda *args, **kwargs: fake_monthly,
    )

    result = app.main(["monthly", "--month", "2026-03", "--space", "PRJ"])

    assert result == 0
    assert fake_monthly.last_month is not None
    assert fake_monthly.last_month.label() == "2026-03"


def test_main_dispatches_sync_sheets_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(google_sheets_ids={2026: "sheet"}))
    fake_sync = FakeSheetsSyncService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_spreadsheet_publisher", lambda settings: object())
    monkeypatch.setattr(
        app,
        "_build_spreadsheet_resolver",
        lambda settings, space: object(),
    )
    monkeypatch.setattr(app, "SheetsSyncService", lambda *args, **kwargs: fake_sync)

    result = app.main(["sync", "sheets", "--date", "2026-03-11", "--space", "project"])

    assert result == 0
    assert str(fake_sync.last_date) == "2026-03-11"


def test_build_source_uses_space_project_key(
    make_space: Callable[..., JiraSpace],
) -> None:
    source = app._build_source(_settings(make_space()), make_space())

    jira_source = cast(JiraWorklogSource, source)
    assert jira_source._project_key == "PRJ"


def test_selected_spaces_supports_key_and_slug(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(
        make_space(key="LA004832", name="Click Price", slug="click-price"),
    )

    assert app._selected_spaces(settings, "LA004832")[0].slug == "click-price"
    assert app._selected_spaces(settings, "click-price")[0].key == "LA004832"


def test_selected_spaces_returns_all_spaces_when_selector_missing(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = AppSettings(
        jira=JiraSettings(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="secret",
        ),
        spaces=(
            make_space(key="LA004832", name="Click Price", slug="click-price"),
            make_space(key="LA009644", name="Data Fixer", slug="data-fixer"),
        ),
        storage=StorageSettings(
            backend="local",
            local_output_dir=Path("reports"),
            bucket_name=None,
            bucket_prefix="jirareport",
        ),
        sheets=SheetsSettings(enabled=True, title_prefix="Jira Worklog Analytics"),
        timezone_name="Europe/Warsaw",
    )

    assert tuple(space.slug for space in app._selected_spaces(settings, None)) == (
        "click-price",
        "data-fixer",
    )


def test_selected_spaces_rejects_unknown_selector(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())

    with pytest.raises(ValueError, match="Unknown Jira space selector"):
        app._selected_spaces(settings, "missing")


def test_build_spreadsheet_helpers_reject_when_disabled(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = AppSettings(
        jira=JiraSettings(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="secret",
        ),
        spaces=(make_space(),),
        storage=StorageSettings(
            backend="local",
            local_output_dir=Path("reports"),
            bucket_name=None,
            bucket_prefix="jirareport",
        ),
        sheets=SheetsSettings(enabled=False, title_prefix="Jira Worklog Analytics"),
        timezone_name="Europe/Warsaw",
    )

    with pytest.raises(ValueError, match="Google Sheets publishing is disabled"):
        app._build_spreadsheet_publisher(settings)
    with pytest.raises(ValueError, match="Google Sheets publishing is disabled"):
        app._build_spreadsheet_resolver(settings, settings.spaces[0])


def test_run_daily_and_monthly_use_current_date_when_input_missing(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_daily = FakeDailyService(None, None, settings.spaces[0], "Europe/Warsaw")
    fake_monthly = FakeMonthlyService(None, None, settings.spaces[0], "Europe/Warsaw")
    monkeypatch.setattr(app, "current_date", lambda timezone: date(2026, 3, 12))
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(
        app,
        "DailySnapshotService",
        lambda *args, **kwargs: fake_daily,
    )
    monkeypatch.setattr(
        app,
        "MonthlyReportService",
        lambda *args, **kwargs: fake_monthly,
    )

    storage = cast(ReportStorage, object())

    assert app._run_daily(None, None, settings, storage) == 0
    assert app._run_monthly(None, None, settings, storage) == 0
    assert fake_daily.last_date == date(2026, 3, 12)
    assert fake_monthly.last_month is not None
    assert fake_monthly.last_month.label() == "2026-03"


def test_run_sync_sheets_uses_current_date_when_input_missing(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(google_sheets_ids={2026: "sheet"}))
    fake_sync = FakeSheetsSyncService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "current_date", lambda timezone: date(2026, 3, 12))
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(
        app,
        "_build_spreadsheet_resolver",
        lambda settings, space: object(),
    )
    monkeypatch.setattr(app, "SheetsSyncService", lambda *args, **kwargs: fake_sync)

    publisher = cast(SpreadsheetPublisher, object())

    assert app._run_sync_sheets(None, None, settings, publisher) == 0
    assert fake_sync.last_date == date(2026, 3, 12)


def _settings(space: JiraSpace) -> AppSettings:
    return AppSettings(
        jira=JiraSettings(
            base_url="https://example.atlassian.net",
            email="user@example.com",
            api_token="secret",
        ),
        spaces=(space,),
        storage=StorageSettings(
            backend="local",
            local_output_dir=Path("reports"),
            bucket_name=None,
            bucket_prefix="jirareport",
        ),
        sheets=SheetsSettings(
            enabled=True,
            title_prefix="Jira Worklog Analytics",
        ),
        timezone_name="Europe/Warsaw",
    )
