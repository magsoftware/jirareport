from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from jirareport.domain.models import JiraSpace, WorklogEntry


@pytest.fixture
def warsaw_timezone() -> ZoneInfo:
    return ZoneInfo("Europe/Warsaw")


@pytest.fixture
def make_worklog(
    warsaw_timezone: ZoneInfo,
) -> Callable[..., WorklogEntry]:
    def _make_worklog(
        worklog_id: str,
        issue_key: str,
        summary: str,
        author_name: str,
        started_at: str,
        duration_seconds: int,
        author_account_id: str | None = None,
        issue_type: str = "Task",
    ) -> WorklogEntry:
        started = datetime.fromisoformat(started_at).astimezone(warsaw_timezone)
        ended = started + timedelta(seconds=duration_seconds)
        return WorklogEntry(
            worklog_id=worklog_id,
            issue_key=issue_key,
            issue_summary=summary,
            issue_type=issue_type,
            author_name=author_name,
            author_account_id=author_account_id,
            started_at=started,
            ended_at=ended,
            duration_seconds=duration_seconds,
        )

    return _make_worklog


@pytest.fixture
def make_space() -> Callable[..., JiraSpace]:
    def _make_space(
        key: str = "PRJ",
        name: str = "Project",
        slug: str = "project",
        board_id: int | None = None,
        google_sheets_ids: dict[int, str] | None = None,
    ) -> JiraSpace:
        return JiraSpace(
            key=key,
            name=name,
            slug=slug,
            board_id=board_id,
            google_sheets_ids=google_sheets_ids,
        )

    return _make_space
