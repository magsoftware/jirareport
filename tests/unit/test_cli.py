from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from jirareport.domain.models import DateRange, JiraSpace, MonthId
from jirareport.domain.ports import (
    CuratedDatasetStorage,
    JsonReportStorage,
    SpreadsheetPublisher,
    WorklogWarehouse,
)
from jirareport.infrastructure.config import (
    AppSettings,
    BigQuerySettings,
    ConfiguredSpace,
    JiraSettings,
    SheetsSettings,
    StorageSettings,
)
from jirareport.infrastructure.jira_client import JiraWorklogSource
from jirareport.interfaces.cli import app


@dataclass(frozen=True)
class DailyResult:
    snapshot_path: str
    curated_paths: tuple[str, ...] = ()
    worklog_count: int = 0


@dataclass(frozen=True)
class MonthlyResult:
    report_path: str
    curated_path: str = "curated/worklogs.parquet"


@dataclass(frozen=True)
class BackfillResult:
    monthly_paths: tuple[str, ...]
    curated_paths: tuple[str, ...]
    worklog_count: int
    month_count: int


@dataclass(frozen=True)
class SyncSheetsResult:
    spreadsheet_urls: tuple[str, ...]
    worklog_count: int = 0


@dataclass
class FakeDailyService:
    source: object
    report_storage: object
    dataset_storage: object
    space: JiraSpace
    timezone_name: str
    last_date: date | None = None

    def generate(self, reference_date: date) -> DailyResult:
        self.last_date = reference_date
        return DailyResult(snapshot_path="raw/daily.json", worklog_count=3)


@dataclass
class FakeMonthlyService:
    source: object
    report_storage: object
    dataset_storage: object
    space: JiraSpace
    timezone_name: str
    last_month: MonthId | None = None

    def generate(self, month: MonthId) -> MonthlyResult:
        self.last_month = month
        return MonthlyResult(report_path="derived/monthly.json")


@dataclass
class FakeBackfillService:
    source: object
    report_storage: object
    dataset_storage: object
    space: JiraSpace
    timezone_name: str
    last_window: object | None = None

    def generate(self, window: object) -> BackfillResult:
        self.last_window = window
        return BackfillResult(
            monthly_paths=("derived/2025-01.json", "derived/2025-02.json"),
            curated_paths=("curated/2025-01.parquet", "curated/2025-02.parquet"),
            worklog_count=10,
            month_count=2,
        )


@dataclass
class FakeSheetsSyncService:
    source: object
    publisher: object
    resolver: object
    space: JiraSpace
    timezone_name: str
    last_date: date | None = None
    last_window: DateRange | None = None

    def generate(self, reference_date: date) -> SyncSheetsResult:
        self.last_date = reference_date
        return SyncSheetsResult(
            spreadsheet_urls=("https://docs.google.com/spreadsheets/d/sheet/edit",),
            worklog_count=3,
        )

    def generate_range(self, window: DateRange) -> SyncSheetsResult:
        self.last_window = window
        return SyncSheetsResult(
            spreadsheet_urls=("https://docs.google.com/spreadsheets/d/sheet/edit",),
            worklog_count=10,
        )


@dataclass
class FakeBigQuerySyncService:
    storage: object
    warehouse: object
    space: JiraSpace
    last_date: date | None = None
    last_window: DateRange | None = None

    def generate(self, reference_date: date) -> object:
        self.last_date = reference_date
        return type(
            "Result",
            (),
            {"months": (MonthId(year=2026, month=3),), "worklog_count": 3},
        )()

    def generate_range(self, window: DateRange) -> object:
        self.last_window = window
        return type(
            "Result",
            (),
            {
                "months": (MonthId(year=2025, month=1), MonthId(year=2025, month=2)),
                "worklog_count": 10,
            },
        )()


def test_main_dispatches_daily_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_daily = FakeDailyService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "flush_logging", lambda: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_json_report_storage", lambda settings: object())
    monkeypatch.setattr(
        app,
        "_build_curated_dataset_storage",
        lambda settings: object(),
    )
    monkeypatch.setattr(app, "DailySnapshotService", lambda *args, **kwargs: fake_daily)

    result = app.main(["daily", "--date", "2026-03-11", "--space", "project"])

    assert result == 0
    assert str(fake_daily.last_date) == "2026-03-11"


def test_main_dispatches_monthly_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_monthly = FakeMonthlyService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "flush_logging", lambda: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_json_report_storage", lambda settings: object())
    monkeypatch.setattr(
        app,
        "_build_curated_dataset_storage",
        lambda settings: object(),
    )
    monkeypatch.setattr(
        app,
        "MonthlyReportService",
        lambda *args, **kwargs: fake_monthly,
    )

    result = app.main(["monthly", "--month", "2026-03", "--space", "PRJ"])

    assert result == 0
    assert fake_monthly.last_month is not None
    assert fake_monthly.last_month.label() == "2026-03"


def test_main_dispatches_backfill_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_backfill = FakeBackfillService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "flush_logging", lambda: None)
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(app, "_build_json_report_storage", lambda settings: object())
    monkeypatch.setattr(
        app,
        "_build_curated_dataset_storage",
        lambda settings: object(),
    )
    monkeypatch.setattr(
        app,
        "BackfillService",
        lambda *args, **kwargs: fake_backfill,
    )

    result = app.main(["backfill", "--from", "2025-01-01", "--to", "2025-12-31", "--space", "project"])

    assert result == 0
    assert fake_backfill.last_window == app._explicit_window("2025-01-01", "2025-12-31")


def test_main_dispatches_sync_sheets_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(), google_sheets_ids={2026: "sheet"})
    fake_sync = FakeSheetsSyncService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "flush_logging", lambda: None)
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


def test_main_dispatches_sync_bigquery_command(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_sync = FakeBigQuerySyncService(object(), object(), settings.spaces[0])
    monkeypatch.setattr(app, "load_settings", lambda: settings)
    monkeypatch.setattr(app, "configure_logging", lambda debug: None)
    monkeypatch.setattr(app, "flush_logging", lambda: None)
    monkeypatch.setattr(
        app,
        "_build_curated_dataset_storage",
        lambda settings: object(),
    )
    monkeypatch.setattr(app, "_build_worklog_warehouse", lambda settings: object())
    monkeypatch.setattr(app, "BigQuerySyncService", lambda *args, **kwargs: fake_sync)

    result = app.main(["sync", "bigquery", "--date", "2026-03-11", "--space", "project"])

    assert result == 0
    assert fake_sync.last_date == date(2026, 3, 11)


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
        bigquery=BigQuerySettings(
            enabled=False,
            project_id=None,
            dataset=None,
            table="worklogs",
        ),
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
        bigquery=BigQuerySettings(
            enabled=False,
            project_id=None,
            dataset=None,
            table="worklogs",
        ),
        timezone_name="Europe/Warsaw",
    )

    with pytest.raises(ValueError, match="Google Sheets publishing is disabled"):
        app._build_spreadsheet_publisher(settings)
    with pytest.raises(ValueError, match="Google Sheets publishing is disabled"):
        app._build_spreadsheet_resolver(settings, settings.spaces[0])


def test_build_worklog_warehouse_rejects_when_disabled(
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
        bigquery=BigQuerySettings(
            enabled=False,
            project_id=None,
            dataset=None,
            table="worklogs",
        ),
        timezone_name="Europe/Warsaw",
    )

    with pytest.raises(ValueError, match="BigQuery reporting is disabled"):
        app._build_worklog_warehouse(settings)


def test_build_storage_helpers_delegate_to_infrastructure_builder(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    captured_calls: list[tuple[str, Path, str | None, str]] = []

    def fake_build_json_storage(
        backend: str,
        root_dir: Path,
        bucket_name: str | None,
        prefix: str,
    ) -> object:
        captured_calls.append((backend, root_dir, bucket_name, prefix))
        return object()

    def fake_build_dataset_storage(
        backend: str,
        root_dir: Path,
        bucket_name: str | None,
        prefix: str,
    ) -> object:
        captured_calls.append((backend, root_dir, bucket_name, prefix))
        return object()

    monkeypatch.setattr(app, "build_json_report_storage", fake_build_json_storage)
    monkeypatch.setattr(
        app,
        "build_curated_dataset_storage",
        fake_build_dataset_storage,
    )

    json_storage = app._build_json_report_storage(settings)
    dataset_storage = app._build_curated_dataset_storage(settings)

    assert json_storage is not None
    assert dataset_storage is not None
    assert captured_calls == [
        ("local", Path("reports"), None, "jirareport"),
        ("local", Path("reports"), None, "jirareport"),
    ]


def test_build_spreadsheet_helpers_return_configured_adapters(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(), google_sheets_ids={2026: "sheet-2026"})
    created: dict[str, object] = {}

    class FakePublisher:
        pass

    class FakeResolver:
        def __init__(self, spreadsheet_ids: dict[int, str], title_prefix: str) -> None:
            created["spreadsheet_ids"] = spreadsheet_ids
            created["title_prefix"] = title_prefix

    monkeypatch.setattr(app, "GoogleSheetsPublisher", FakePublisher)
    monkeypatch.setattr(app, "GoogleSheetsResolver", FakeResolver)

    publisher = app._build_spreadsheet_publisher(settings)
    resolver = app._build_spreadsheet_resolver(settings, settings.spaces[0])

    assert isinstance(publisher, FakePublisher)
    assert isinstance(resolver, FakeResolver)
    assert created == {
        "spreadsheet_ids": {2026: "sheet-2026"},
        "title_prefix": "Jira Worklog Analytics - Project",
    }


def test_build_worklog_warehouse_rejects_missing_project_or_dataset(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    settings = AppSettings(
        jira=settings.jira,
        spaces=settings.spaces,
        storage=settings.storage,
        sheets=settings.sheets,
        bigquery=BigQuerySettings(
            enabled=True,
            project_id=None,
            dataset="jirareport",
            table="worklogs",
        ),
        timezone_name=settings.timezone_name,
    )

    with pytest.raises(
        ValueError,
        match="BigQuery project and dataset must be configured",
    ):
        app._build_worklog_warehouse(settings)

    settings = AppSettings(
        jira=settings.jira,
        spaces=settings.spaces,
        storage=settings.storage,
        sheets=settings.sheets,
        bigquery=BigQuerySettings(
            enabled=True,
            project_id="jira-report-489919",
            dataset=None,
            table="worklogs",
        ),
        timezone_name=settings.timezone_name,
    )

    with pytest.raises(
        ValueError,
        match="BigQuery project and dataset must be configured",
    ):
        app._build_worklog_warehouse(settings)


def test_build_worklog_warehouse_returns_bigquery_adapter(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    settings = AppSettings(
        jira=settings.jira,
        spaces=settings.spaces,
        storage=settings.storage,
        sheets=settings.sheets,
        bigquery=BigQuerySettings(
            enabled=True,
            project_id="jira-report-489919",
            dataset="jirareport",
            table="monthly_worklogs",
        ),
        timezone_name=settings.timezone_name,
    )
    captured: dict[str, object] = {}

    class FakeWarehouse:
        def __init__(
            self,
            project_id: str,
            dataset: str,
            spaces: tuple[JiraSpace, ...],
            table: str,
        ) -> None:
            captured["project_id"] = project_id
            captured["dataset"] = dataset
            captured["spaces"] = spaces
            captured["table"] = table

    monkeypatch.setattr(app, "BigQueryWorklogWarehouse", FakeWarehouse)

    warehouse = app._build_worklog_warehouse(settings)

    assert isinstance(warehouse, FakeWarehouse)
    assert captured == {
        "project_id": "jira-report-489919",
        "dataset": "jirareport",
        "spaces": settings.spaces,
        "table": "monthly_worklogs",
    }


def test_run_daily_and_monthly_use_current_date_when_input_missing(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_daily = FakeDailyService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    fake_monthly = FakeMonthlyService(
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
        "DailySnapshotService",
        lambda *args, **kwargs: fake_daily,
    )
    monkeypatch.setattr(
        app,
        "MonthlyReportService",
        lambda *args, **kwargs: fake_monthly,
    )

    report_storage = cast(JsonReportStorage, object())
    dataset_storage = cast(CuratedDatasetStorage, object())

    assert (
        app._run_daily(
            None,
            None,
            settings,
            app._build_source,
            report_storage,
            dataset_storage,
        )
        == 0
    )
    assert (
        app._run_monthly(
            None,
            None,
            settings,
            app._build_source,
            report_storage,
            dataset_storage,
        )
        == 0
    )
    assert fake_daily.last_date == date(2026, 3, 12)
    assert fake_monthly.last_month is not None
    assert fake_monthly.last_month.label() == "2026-03"


def test_explicit_window_parses_cli_range() -> None:
    assert app._explicit_window("2025-01-01", "2025-12-31") == DateRange(
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )


def test_explicit_window_optional_handles_missing_or_partial_boundaries() -> None:
    assert app._explicit_window_optional(None, None) is None

    with pytest.raises(ValueError, match="Both --from and --to are required"):
        app._explicit_window_optional("2025-01-01", None)

    with pytest.raises(ValueError, match="Both --from and --to are required"):
        app._explicit_window_optional(None, "2025-12-31")


def test_run_sync_sheets_uses_current_date_when_input_missing(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(), google_sheets_ids={2026: "sheet"})
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

    assert (
        app._run_sync_sheets(
            None,
            None,
            None,
            None,
            settings,
            app._build_source,
            publisher,
        )
        == 0
    )
    assert fake_sync.last_date == date(2026, 3, 12)


def test_run_sync_sheets_uses_explicit_range_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(), google_sheets_ids={2025: "sheet"})
    fake_sync = FakeSheetsSyncService(
        None,
        None,
        None,
        settings.spaces[0],
        "Europe/Warsaw",
    )
    monkeypatch.setattr(app, "_build_source", lambda settings, space: object())
    monkeypatch.setattr(
        app,
        "_build_spreadsheet_resolver",
        lambda settings, space: object(),
    )
    monkeypatch.setattr(app, "SheetsSyncService", lambda *args, **kwargs: fake_sync)

    publisher = cast(SpreadsheetPublisher, object())

    assert (
        app._run_sync_sheets(
            None,
            "2025-01-01",
            "2025-12-31",
            None,
            settings,
            app._build_source,
            publisher,
        )
        == 0
    )
    assert fake_sync.last_window == DateRange(
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )


def test_run_sync_sheets_rejects_date_and_explicit_range_together(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space(), google_sheets_ids={2025: "sheet"})
    publisher = cast(SpreadsheetPublisher, object())

    with pytest.raises(ValueError, match="Use either --date or --from/--to"):
        app._run_sync_sheets(
            "2026-03-11",
            "2025-01-01",
            "2025-12-31",
            None,
            settings,
            app._build_source,
            publisher,
        )


def test_run_sync_bigquery_uses_current_date_when_input_missing(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_sync = FakeBigQuerySyncService(object(), object(), settings.spaces[0])
    monkeypatch.setattr(app, "current_date", lambda timezone: date(2026, 3, 12))
    monkeypatch.setattr(app, "BigQuerySyncService", lambda *args, **kwargs: fake_sync)

    dataset_storage = cast(CuratedDatasetStorage, object())
    warehouse = cast(WorklogWarehouse, object())

    assert (
        app._run_sync_bigquery(
            None,
            None,
            None,
            None,
            settings,
            dataset_storage,
            warehouse,
        )
        == 0
    )
    assert fake_sync.last_date == date(2026, 3, 12)


def test_run_sync_bigquery_uses_explicit_range_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    fake_sync = FakeBigQuerySyncService(object(), object(), settings.spaces[0])
    monkeypatch.setattr(app, "BigQuerySyncService", lambda *args, **kwargs: fake_sync)

    dataset_storage = cast(CuratedDatasetStorage, object())
    warehouse = cast(WorklogWarehouse, object())

    assert (
        app._run_sync_bigquery(
            None,
            "2025-01-01",
            "2025-12-31",
            None,
            settings,
            dataset_storage,
            warehouse,
        )
        == 0
    )
    assert fake_sync.last_window == DateRange(
        start=date(2025, 1, 1),
        end=date(2025, 12, 31),
    )


def test_run_sync_bigquery_rejects_date_and_explicit_range_together(
    make_space: Callable[..., JiraSpace],
) -> None:
    settings = _settings(make_space())
    dataset_storage = cast(CuratedDatasetStorage, object())
    warehouse = cast(WorklogWarehouse, object())

    with pytest.raises(ValueError, match="Use either --date or --from/--to"):
        app._run_sync_bigquery(
            "2026-03-11",
            "2025-01-01",
            "2025-12-31",
            None,
            settings,
            dataset_storage,
            warehouse,
        )


def _settings(
    space: JiraSpace,
    *,
    board_id: int | None = None,
    google_sheets_ids: dict[int, str] | None = None,
) -> AppSettings:
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
        bigquery=BigQuerySettings(
            enabled=False,
            project_id=None,
            dataset=None,
            table="worklogs",
        ),
        timezone_name="Europe/Warsaw",
        configured_spaces=(
            ConfiguredSpace(
                space=space,
                board_id=board_id,
                google_sheets_ids=tuple(sorted((google_sheets_ids or {}).items())),
            ),
        ),
    )
