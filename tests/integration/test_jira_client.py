"""Integration scenarios for the Jira worklog adapter.

Goal
- Validate the real `JiraWorklogSource` adapter against realistic paginated Jira
  payloads without calling the live Jira API.
- Prove that issue search, per-issue worklog pagination, timezone conversion,
  and issue metadata mapping stay consistent with the reporting contract.

Fixtures
- `FakeSession` replays a sequence of HTTP responses and records every request
  URL, params, and timeout used by the adapter.
- `FakeResponse` returns static JSON payloads so the tests can model Jira search
  pages and issue worklog pages deterministically.
- Helper builders create Jira-like worklog payloads with optional issue type
  and author account metadata.

Scenarios
1. Issue search pagination and timezone filtering cooperate so only worklogs in
   the requested local date window are returned.
2. A single issue with multiple worklog pages is fully traversed before the
   adapter moves on, preserving all matching rows.
3. Missing `issuetype` and missing `author.accountId` are normalized to
   `Unknown` and `None` respectively.
4. A worklog crossing midnight in the reporting timezone is mapped with
   correct derived end date and `crosses_midnight=True`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from jirareport.domain.models import DateRange
from jirareport.infrastructure.jira_client import JiraWorklogSource, RequestParams

_UNSET_ACCOUNT_ID = object()


class FakeResponse:
    """Wraps one static Jira payload returned by the fake HTTP session."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        """Simulates a successful HTTP response."""
        return None

    def json(self) -> object:
        """Returns the configured JSON payload."""
        return self._payload


class FakeSession:
    """Replays a predefined sequence of Jira API responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, RequestParams | None, int]] = []

    def get(
        self,
        url: str,
        params: RequestParams | None = None,
        timeout: int = 30,
    ) -> FakeResponse:
        """Returns the next queued response and records request metadata."""
        self.calls.append((url, params, timeout))
        return self._responses.pop(0)


def test_fetch_worklogs_handles_pagination_and_timezone_filtering() -> None:
    """Scenario
    Given a paginated Jira issue search and multiple issue worklog pages
    When the adapter fetches worklogs for a local reporting window
    Then only worklogs whose local start date falls into that window are
    returned, along with their mapped Jira issue types.
    """

    session = FakeSession(
        [
            FakeResponse(
                {
                    "issues": [
                        {
                            "key": "PRJ-1",
                            "fields": {
                                "summary": "First issue",
                                "issuetype": {"name": "Bug"},
                            },
                        }
                    ],
                    "isLast": False,
                    "nextPageToken": "page-2-token",
                }
            ),
            FakeResponse(
                {
                    "issues": [
                        {
                            "key": "PRJ-2",
                            "fields": {
                                "summary": "Second issue",
                                "issuetype": {"name": "Story"},
                            },
                        }
                    ],
                    "isLast": True,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("1", "2026-02-28T23:30:00.000+0000", 3600, "Alice"),
                    ],
                    "total": 2,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("2", "2026-02-27T20:00:00.000+0000", 1800, "Alice"),
                    ],
                    "total": 2,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("3", "2026-03-10T09:00:00.000+0100", 7200, "Bob"),
                    ],
                    "total": 1,
                }
            ),
        ]
    )
    source = _source(session)

    result = source.fetch_worklogs(DateRange(date(2026, 3, 1), date(2026, 3, 11)))

    assert [entry.worklog_id for entry in result] == ["1", "3"]
    assert result[0].started_at.date().isoformat() == "2026-03-01"
    assert result[0].issue_type == "Bug"
    assert result[1].issue_type == "Story"
    assert result[1].author_name == "Bob"
    assert len(session.calls) == 5
    assert session.calls[1][1] == {
        "jql": (
            'project = "PRJ" AND worklogDate >= "2026-03-01" '
            'AND worklogDate <= "2026-03-11" ORDER BY created DESC'
        ),
        "maxResults": 100,
        "fields": "summary,issuetype",
        "nextPageToken": "page-2-token",
    }


def test_fetch_worklogs_traverses_multiple_worklog_pages_for_one_issue() -> None:
    """Scenario
    Given a single Jira issue whose worklogs span multiple paginated responses
    When the adapter fetches the reporting window for that issue
    Then all matching worklogs from every worklog page are returned in order.
    """

    session = FakeSession(
        [
            FakeResponse(
                {
                    "issues": [
                        {
                            "key": "PRJ-1",
                            "fields": {
                                "summary": "Paged issue",
                                "issuetype": {"name": "Task"},
                            },
                        }
                    ],
                    "isLast": True,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("1", "2026-03-05T09:00:00.000+0100", 3600, "Alice"),
                    ],
                    "total": 2,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("2", "2026-03-06T11:00:00.000+0100", 1800, "Alice"),
                    ],
                    "total": 2,
                }
            ),
        ]
    )
    source = _source(session)

    result = source.fetch_worklogs(DateRange(date(2026, 3, 1), date(2026, 3, 31)))

    assert [entry.worklog_id for entry in result] == ["1", "2"]
    assert all(entry.issue_type == "Task" for entry in result)
    assert session.calls[1][1] == {"startAt": 0, "maxResults": 100}
    assert session.calls[2][1] == {"startAt": 1, "maxResults": 100}


def test_fetch_worklogs_defaults_unknown_issue_type_and_missing_account_id() -> None:
    """Scenario
    Given Jira payloads with missing `issuetype` and missing `author.accountId`
    When the adapter normalizes issues and worklogs
    Then issue type falls back to `Unknown` and author account ID becomes `None`.
    """

    session = FakeSession(
        [
            FakeResponse(
                {
                    "issues": [
                        {
                            "key": "PRJ-1",
                            "fields": {
                                "summary": "Issue without type",
                            },
                        }
                    ],
                    "isLast": True,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog(
                            "1",
                            "2026-03-05T09:00:00.000+0100",
                            3600,
                            "Alice",
                            account_id=None,
                        ),
                    ],
                    "total": 1,
                }
            ),
        ]
    )
    source = _source(session)

    result = source.fetch_worklogs(DateRange(date(2026, 3, 1), date(2026, 3, 31)))

    assert len(result) == 1
    assert result[0].issue_type == "Unknown"
    assert result[0].author_account_id is None


def test_fetch_worklogs_marks_crossing_midnight_after_timezone_conversion() -> None:
    """Scenario
    Given a Jira worklog that crosses midnight in the reporting timezone
    When the adapter maps it to the normalized domain model
    Then the derived end date changes and `crosses_midnight` becomes true.
    """

    session = FakeSession(
        [
            FakeResponse(
                {
                    "issues": [
                        {
                            "key": "PRJ-1",
                            "fields": {
                                "summary": "Night shift",
                                "issuetype": {"name": "Test"},
                            },
                        }
                    ],
                    "isLast": True,
                }
            ),
            FakeResponse(
                {
                    "worklogs": [
                        _worklog("1", "2026-03-11T23:30:00.000+0100", 7200, "Alice"),
                    ],
                    "total": 1,
                }
            ),
        ]
    )
    source = _source(session)

    result = source.fetch_worklogs(DateRange(date(2026, 3, 11), date(2026, 3, 12)))

    assert len(result) == 1
    assert result[0].started_date.isoformat() == "2026-03-11"
    assert result[0].ended_date.isoformat() == "2026-03-12"
    assert result[0].crosses_midnight is True


def _source(session: FakeSession) -> JiraWorklogSource:
    """Builds the Jira adapter with a shared fake session."""
    return JiraWorklogSource(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="secret",
        project_key="PRJ",
        timezone_name="Europe/Warsaw",
        session=session,
    )


def _worklog(
    worklog_id: str,
    started: str,
    seconds: int,
    author_name: str,
    account_id: object = _UNSET_ACCOUNT_ID,
) -> dict[str, Any]:
    """Builds one Jira-like worklog payload used by adapter integration tests."""
    if account_id is _UNSET_ACCOUNT_ID:
        account_id = f"{author_name}-1"
    author: dict[str, Any] = {"displayName": author_name}
    if account_id is not None:
        author["accountId"] = account_id
    return {
        "id": worklog_id,
        "started": started,
        "timeSpentSeconds": seconds,
        "author": author,
    }
