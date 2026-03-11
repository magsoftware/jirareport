from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, order=True)
class MonthId:
    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= self.month <= 12:
            raise ValueError("Month must be in range 1..12.")

    @classmethod
    def from_date(cls, value: date) -> MonthId:
        return cls(year=value.year, month=value.month)

    @classmethod
    def parse(cls, value: str) -> MonthId:
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid month format: {value}")
        return cls(year=int(parts[0]), month=int(parts[1]))

    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    def next_month(self) -> MonthId:
        if self.month == 12:
            return MonthId(year=self.year + 1, month=1)
        return MonthId(year=self.year, month=self.month + 1)

    def previous_month(self) -> MonthId:
        if self.month == 1:
            return MonthId(year=self.year - 1, month=12)
        return MonthId(year=self.year, month=self.month - 1)

    def contains(self, value: date) -> bool:
        return self.year == value.year and self.month == value.month


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("DateRange end must not be before start.")

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


@dataclass(frozen=True)
class Issue:
    key: str
    summary: str


@dataclass(frozen=True)
class WorklogEntry:
    worklog_id: str
    issue_key: str
    issue_summary: str
    author_name: str
    author_account_id: str | None
    started_at: datetime
    ended_at: datetime
    duration_seconds: int

    @property
    def duration_hours(self) -> float:
        return round(self.duration_seconds / 3600, 2)

    @property
    def started_date(self) -> date:
        return self.started_at.date()

    @property
    def ended_date(self) -> date:
        return self.ended_at.date()

    @property
    def crosses_midnight(self) -> bool:
        return self.started_date != self.ended_date


@dataclass(frozen=True)
class DailyRawSnapshot:
    project_key: str
    snapshot_date: date
    window: DateRange
    generated_at: datetime
    timezone_name: str
    worklogs: tuple[WorklogEntry, ...]


@dataclass(frozen=True)
class TicketWorklogReport:
    issue_key: str
    summary: str
    bookings: tuple[WorklogEntry, ...]

    @property
    def total_duration_hours(self) -> float:
        total_seconds = sum(entry.duration_seconds for entry in self.bookings)
        return round(total_seconds / 3600, 2)


@dataclass(frozen=True)
class MonthlyWorklogReport:
    project_key: str
    month: MonthId
    generated_at: datetime
    timezone_name: str
    tickets: tuple[TicketWorklogReport, ...]
