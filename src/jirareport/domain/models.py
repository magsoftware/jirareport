from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, order=True)
class MonthId:
    """Represents a calendar month used by reporting use cases.

    The application uses this value object instead of raw strings to keep
    month parsing, navigation, and validation in one place.
    """

    year: int
    month: int

    def __post_init__(self) -> None:
        """Validates that the month number is within the calendar range."""
        if not 1 <= self.month <= 12:
            raise ValueError("Month must be in range 1..12.")

    @classmethod
    def from_date(cls, value: date) -> MonthId:
        """Builds a month identifier from a date instance."""
        return cls(year=value.year, month=value.month)

    @classmethod
    def parse(cls, value: str) -> MonthId:
        """Parses a month in YYYY-MM format.

        Args:
            value: String representation of the month.

        Returns:
            Parsed month identifier.

        Raises:
            ValueError: If the input does not follow YYYY-MM format.
        """
        parts = value.split("-")
        if len(parts) != 2:
            raise ValueError(f"Invalid month format: {value}")
        return cls(year=int(parts[0]), month=int(parts[1]))

    def label(self) -> str:
        """Returns the canonical YYYY-MM label for the month."""
        return f"{self.year:04d}-{self.month:02d}"

    def first_day(self) -> date:
        """Returns the first day of the represented month."""
        return date(self.year, self.month, 1)

    def next_month(self) -> MonthId:
        """Returns the next calendar month."""
        if self.month == 12:
            return MonthId(year=self.year + 1, month=1)
        return MonthId(year=self.year, month=self.month + 1)

    def previous_month(self) -> MonthId:
        """Returns the previous calendar month."""
        if self.month == 1:
            return MonthId(year=self.year - 1, month=12)
        return MonthId(year=self.year, month=self.month - 1)

    def contains(self, value: date) -> bool:
        """Checks whether a given date belongs to this month."""
        return self.year == value.year and self.month == value.month


@dataclass(frozen=True)
class DateRange:
    """Represents an inclusive range of calendar dates."""

    start: date
    end: date

    def __post_init__(self) -> None:
        """Validates that the range boundaries are ordered."""
        if self.end < self.start:
            raise ValueError("DateRange end must not be before start.")

    def contains(self, value: date) -> bool:
        """Checks whether a date falls inside the range."""
        return self.start <= value <= self.end


@dataclass(frozen=True)
class Issue:
    """Represents the minimal Jira issue data needed for reporting."""

    key: str
    summary: str


@dataclass(frozen=True)
class WorklogEntry:
    """Represents a single normalized Jira worklog entry.

    The model already contains the calculated end time, derived from the Jira
    start timestamp and duration, so downstream layers do not need to repeat
    that calculation.
    """

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
        """Returns the duration in hours rounded for reporting output."""
        return round(self.duration_seconds / 3600, 2)

    @property
    def started_date(self) -> date:
        """Returns the local calendar date of the worklog start."""
        return self.started_at.date()

    @property
    def ended_date(self) -> date:
        """Returns the local calendar date of the worklog end."""
        return self.ended_at.date()

    @property
    def crosses_midnight(self) -> bool:
        """Indicates whether the worklog crosses a date boundary."""
        return self.started_date != self.ended_date


@dataclass(frozen=True)
class DailyRawSnapshot:
    """Represents the raw output of the main daily reporting use case."""

    project_key: str
    snapshot_date: date
    window: DateRange
    generated_at: datetime
    timezone_name: str
    worklogs: tuple[WorklogEntry, ...]


@dataclass(frozen=True)
class TicketWorklogReport:
    """Represents all worklogs grouped under a single ticket."""

    issue_key: str
    summary: str
    bookings: tuple[WorklogEntry, ...]

    @property
    def total_duration_hours(self) -> float:
        """Returns the total duration of all grouped worklogs in hours."""
        total_seconds = sum(entry.duration_seconds for entry in self.bookings)
        return round(total_seconds / 3600, 2)


@dataclass(frozen=True)
class MonthlyWorklogReport:
    """Represents the derived monthly report for a single calendar month."""

    project_key: str
    month: MonthId
    generated_at: datetime
    timezone_name: str
    tickets: tuple[TicketWorklogReport, ...]
