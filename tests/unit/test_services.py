from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from jirareport.application.parquet_serializers import serialize_monthly_worklogs
from jirareport.application.services import (
    BackfillService,
    BigQuerySyncService,
    DailySnapshotService,
    MonthlyReportService,
    SheetsSyncService,
)
from jirareport.domain.models import (
    DateRange,
    JiraSpace,
    MonthId,
    SpreadsheetPublishRequest,
    SpreadsheetTarget,
    WorklogEntry,
)


class FakeWorklogSource:
    def __init__(self, worklogs: list[WorklogEntry]) -> None:
        self._worklogs = worklogs
        self.windows: list[DateRange] = []

    def fetch_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        self.windows.append(window)
        return list(self._worklogs)


class FakeStorage:
    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}
        self.binary_payloads: dict[str, bytes] = {}

    def write_json(self, path: str, payload: dict[str, Any]) -> str:
        self.payloads[path] = payload
        return path

    def write_parquet(self, path: str, payload: bytes) -> str:
        self.binary_payloads[path] = payload
        return path

    def read_bytes(self, path: str) -> bytes:
        return self.binary_payloads[path]


class FakeSpreadsheetPublisher:
    def __init__(self) -> None:
        self.requests: list[SpreadsheetPublishRequest] = []

    def publish(self, request: SpreadsheetPublishRequest) -> str:
        self.requests.append(request)
        return f"https://docs.google.com/spreadsheets/d/{request.spreadsheet_id}/edit"


class FakeSpreadsheetResolver:
    def __init__(self, mapping: dict[int, str]) -> None:
        self.mapping = mapping
        self.years: list[int] = []

    def resolve(self, year: int) -> SpreadsheetTarget:
        self.years.append(year)
        return SpreadsheetTarget(
            year=year,
            spreadsheet_id=self.mapping[year],
            spreadsheet_url=f"https://docs.google.com/spreadsheets/d/{self.mapping[year]}/edit",
        )


class FakeWorklogWarehouse:
    def __init__(self) -> None:
        self.loads: list[tuple[str, str, bytes]] = []
        self.views_ensured = False

    def load_monthly_worklogs(
        self,
        space: JiraSpace,
        month: MonthId,
        parquet_payload: bytes,
    ) -> None:
        self.loads.append((space.slug, month.label(), parquet_payload))

    def ensure_views(self) -> None:
        self.views_ensured = True


def test_daily_snapshot_generates_raw_and_monthly_reports(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "February bugfix",
            "Alice",
            "2026-02-28T23:30:00+00:00",
            3600,
        ),
        make_worklog(
            "2",
            "PRJ-1",
            "February bugfix",
            "Alice",
            "2026-03-03T08:00:00+01:00",
            7200,
        ),
        make_worklog(
            "3",
            "PRJ-2",
            "March task",
            "Bob",
            "2026-03-10T09:00:00+01:00",
            1800,
        ),
    ]
    source = FakeWorklogSource(worklogs)
    storage = FakeStorage()
    space = make_space(key="PRJ", name="Project", slug="project")
    service = DailySnapshotService(source, storage, storage, space, "Europe/Warsaw")

    result = service.generate(date(2026, 3, 11))

    assert (
        result.snapshot_path
        == "spaces/PRJ/project/raw/daily/2026/03/2026-03-11.json"
    )
    assert result.monthly_paths == (
        "spaces/PRJ/project/derived/monthly/2026/2026-02.json",
        "spaces/PRJ/project/derived/monthly/2026/2026-03.json",
    )
    assert result.curated_paths == (
        "curated/worklogs/space=project/year=2026/month=02/worklogs.parquet",
        "curated/worklogs/space=project/year=2026/month=03/worklogs.parquet",
    )
    assert source.windows == [DateRange(start=date(2026, 2, 1), end=date(2026, 3, 11))]
    raw_payload = storage.payloads[result.snapshot_path]
    assert raw_payload["report_type"] == "daily_raw_snapshot"
    assert raw_payload["space"]["slug"] == "project"
    assert len(raw_payload["worklogs"]) == 3
    assert raw_payload["worklogs"][0]["issue_type"] == "Task"
    march_payload = storage.payloads[
        "spaces/PRJ/project/derived/monthly/2026/2026-03.json"
    ]
    issue_keys = [ticket["issue_key"] for ticket in march_payload["tickets"]]
    assert issue_keys == ["PRJ-1", "PRJ-2"]
    assert len(march_payload["tickets"][0]["bookings"]) == 2
    assert march_payload["tickets"][0]["issue_type"] == "Task"
    assert march_payload["tickets"][0]["bookings"][0]["author"] == "Alice"
    assert march_payload["tickets"][0]["bookings"][0]["started_date"] == "2026-03-01"
    assert march_payload["tickets"][0]["bookings"][0]["crosses_midnight"] is False
    assert result.curated_paths[1] in storage.binary_payloads


def test_daily_snapshot_closes_previous_two_months_on_first_day_of_month(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "February work",
            "Alice",
            "2026-02-20T09:00:00+01:00",
            3600,
        ),
        make_worklog(
            "2",
            "PRJ-2",
            "March work",
            "Bob",
            "2026-03-20T09:00:00+01:00",
            3600,
        ),
    ]
    source = FakeWorklogSource(worklogs)
    storage = FakeStorage()
    space = make_space(key="PRJ", name="Project", slug="project")
    service = DailySnapshotService(source, storage, storage, space, "Europe/Warsaw")

    result = service.generate(date(2026, 4, 1))

    assert source.windows == [DateRange(start=date(2026, 2, 1), end=date(2026, 3, 31))]
    assert result.monthly_paths == (
        "spaces/PRJ/project/derived/monthly/2026/2026-02.json",
        "spaces/PRJ/project/derived/monthly/2026/2026-03.json",
    )
    assert result.curated_paths == (
        "curated/worklogs/space=project/year=2026/month=02/worklogs.parquet",
        "curated/worklogs/space=project/year=2026/month=03/worklogs.parquet",
    )


def test_monthly_report_filters_to_requested_month(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "Late February work",
            "Alice",
            "2026-02-20T09:00:00+01:00",
            3600,
        ),
        make_worklog(
            "2",
            "PRJ-1",
            "March work",
            "Alice",
            "2026-03-03T09:00:00+01:00",
            7200,
        ),
    ]
    source = FakeWorklogSource(worklogs)
    storage = FakeStorage()
    space = make_space(key="PRJ", name="Project", slug="project")
    service = MonthlyReportService(source, storage, storage, space, "Europe/Warsaw")

    result = service.generate(MonthId(year=2026, month=3))

    assert result.report_path == "spaces/PRJ/project/derived/monthly/2026/2026-03.json"
    assert (
        result.curated_path
        == "curated/worklogs/space=project/year=2026/month=03/worklogs.parquet"
    )
    assert result.ticket_count == 1
    payload = storage.payloads[result.report_path]
    assert payload["month"] == "2026-03"
    assert len(payload["tickets"]) == 1
    assert payload["tickets"][0]["issue_type"] == "Task"
    assert payload["tickets"][0]["bookings"][0]["duration_hours"] == 2.0
    assert result.curated_path in storage.binary_payloads


def test_backfill_generates_monthly_reports_for_explicit_range(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "January work",
            "Alice",
            "2025-01-15T09:00:00+01:00",
            3600,
        ),
        make_worklog(
            "2",
            "PRJ-2",
            "February work",
            "Bob",
            "2025-02-03T09:00:00+01:00",
            7200,
        ),
    ]
    source = FakeWorklogSource(worklogs)
    storage = FakeStorage()
    space = make_space(key="PRJ", name="Project", slug="project")
    service = BackfillService(source, storage, storage, space, "Europe/Warsaw")

    result = service.generate(DateRange(start=date(2025, 1, 1), end=date(2025, 2, 28)))

    assert result.month_count == 2
    assert result.worklog_count == 2
    assert source.windows == [DateRange(start=date(2025, 1, 1), end=date(2025, 2, 28))]
    assert result.monthly_paths == (
        "spaces/PRJ/project/derived/monthly/2025/2025-01.json",
        "spaces/PRJ/project/derived/monthly/2025/2025-02.json",
    )
    assert result.curated_paths == (
        "curated/worklogs/space=project/year=2025/month=01/worklogs.parquet",
        "curated/worklogs/space=project/year=2025/month=02/worklogs.parquet",
    )


def test_sync_sheets_builds_yearly_tabs_from_current_snapshot(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "February bugfix",
            "Alice",
            "2026-02-20T09:00:00+01:00",
            3600,
            "alice-1",
        ),
        make_worklog(
            "2",
            "PRJ-1",
            "March bugfix",
            "Alice",
            "2026-03-03T09:00:00+01:00",
            7200,
            "alice-1",
        ),
        make_worklog(
            "3",
            "PRJ-2",
            "March task",
            "Bob",
            "2026-03-10T11:00:00+01:00",
            1800,
            "bob-1",
        ),
    ]
    source = FakeWorklogSource(worklogs)
    publisher = FakeSpreadsheetPublisher()
    resolver = FakeSpreadsheetResolver({2026: "sheet-2026"})
    space = make_space(key="PRJ", name="Project", slug="project")
    service = SheetsSyncService(
        source=source,
        publisher=publisher,
        resolver=resolver,
        space=space,
        timezone_name="Europe/Warsaw",
    )

    result = service.generate(date(2026, 3, 11))

    assert result.spreadsheet_urls == (
        "https://docs.google.com/spreadsheets/d/sheet-2026/edit",
    )
    assert len(publisher.requests) == 1
    assert resolver.years == [2026]
    request = publisher.requests[0]
    assert request.year == 2026
    assert tuple(worksheet.title for worksheet in request.worksheets) == ("02", "03")
    february_tab = request.worksheets[0]
    assert february_tab.rows[0][0] == "snapshot_date"
    assert february_tab.rows[1][5] == "2026-02"
    assert february_tab.rows[1][6] == "PRJ-1"
    assert february_tab.rows[1][8] == "Task"
    march_tab = request.worksheets[1]
    assert march_tab.rows[0][0] == "snapshot_date"
    assert march_tab.rows[1][5] == "2026-03"
    assert march_tab.rows[1][6] == "PRJ-1"
    assert march_tab.rows[2][6] == "PRJ-2"


def test_sync_sheets_range_builds_monthly_tabs_for_explicit_window(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    worklogs = [
        make_worklog(
            "1",
            "PRJ-1",
            "January task",
            "Alice",
            "2025-01-10T09:00:00+01:00",
            3600,
            "alice-1",
        ),
        make_worklog(
            "2",
            "PRJ-2",
            "February task",
            "Bob",
            "2025-02-03T10:00:00+01:00",
            7200,
            "bob-1",
        ),
    ]
    source = FakeWorklogSource(worklogs)
    publisher = FakeSpreadsheetPublisher()
    resolver = FakeSpreadsheetResolver({2025: "sheet-2025"})
    space = make_space(key="PRJ", name="Project", slug="project")
    service = SheetsSyncService(
        source=source,
        publisher=publisher,
        resolver=resolver,
        space=space,
        timezone_name="Europe/Warsaw",
    )

    result = service.generate_range(
        DateRange(start=date(2025, 1, 1), end=date(2025, 2, 28))
    )

    assert result.spreadsheet_urls == (
        "https://docs.google.com/spreadsheets/d/sheet-2025/edit",
    )
    assert resolver.years == [2025]
    request = publisher.requests[0]
    assert tuple(worksheet.title for worksheet in request.worksheets) == ("01", "02")


def test_bigquery_sync_loads_active_months_from_curated_storage(
    make_worklog: Callable[..., WorklogEntry],
    make_space: Callable[..., JiraSpace],
) -> None:
    storage = FakeStorage()
    space = make_space(key="PRJ", name="Project", slug="project")
    storage.binary_payloads[
        "curated/worklogs/space=project/year=2026/month=02/worklogs.parquet"
    ] = serialize_monthly_worklogs(
        space,
        MonthId(year=2026, month=2),
        [
            make_worklog(
                "feb-1",
                "PRJ-1",
                "February work",
                "Alice",
                "2026-02-20T09:00:00+01:00",
                3600,
            )
        ],
    )
    storage.binary_payloads[
        "curated/worklogs/space=project/year=2026/month=03/worklogs.parquet"
    ] = serialize_monthly_worklogs(
        space,
        MonthId(year=2026, month=3),
        [
            make_worklog(
                "mar-1",
                "PRJ-2",
                "March work",
                "Bob",
                "2026-03-10T09:00:00+01:00",
                7200,
            )
        ],
    )
    warehouse = FakeWorklogWarehouse()
    service = BigQuerySyncService(
        dataset_storage=storage,
        warehouse=warehouse,
        space=space,
    )

    result = service.generate(date(2026, 4, 1))

    assert result.months == (
        MonthId(year=2026, month=2),
        MonthId(year=2026, month=3),
    )
    assert result.worklog_count == 2
    assert warehouse.loads == [
        (
            "project",
            "2026-02",
            storage.binary_payloads[
                "curated/worklogs/space=project/year=2026/month=02/worklogs.parquet"
            ],
        ),
        (
            "project",
            "2026-03",
            storage.binary_payloads[
                "curated/worklogs/space=project/year=2026/month=03/worklogs.parquet"
            ],
        ),
    ]
    assert warehouse.views_ensured is True
