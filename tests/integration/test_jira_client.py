from __future__ import annotations

from datetime import date
from typing import Any

from jirareport.domain.models import DateRange
from jirareport.infrastructure.jira_client import JiraWorklogSource, RequestParams


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, RequestParams | None, int]] = []

    def get(
        self,
        url: str,
        params: RequestParams | None = None,
        timeout: int = 30,
    ) -> FakeResponse:
        self.calls.append((url, params, timeout))
        return self._responses.pop(0)


def test_fetch_worklogs_handles_pagination_and_timezone_filtering() -> None:
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
    source = JiraWorklogSource(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="secret",
        project_key="PRJ",
        timezone_name="Europe/Warsaw",
        session=session,
    )

    result = source.fetch_worklogs(DateRange(date(2026, 3, 1), date(2026, 3, 11)))

    assert [entry.worklog_id for entry in result] == ["1", "3"]
    assert result[0].started_at.date().isoformat() == "2026-03-01"
    assert result[0].issue_type == "Bug"
    assert result[1].issue_type == "Story"
    assert result[1].author_name == "Bob"
    assert len(session.calls) == 5
    assert session.calls[1][1] == {
        "jql": 'project = "PRJ" AND worklogDate >= "2026-03-01" AND worklogDate <= "2026-03-11" ORDER BY created DESC',
        "maxResults": 100,
        "fields": "summary,issuetype",
        "nextPageToken": "page-2-token",
    }


def _worklog(
    worklog_id: str,
    started: str,
    seconds: int,
    author_name: str,
) -> dict[str, Any]:
    return {
        "id": worklog_id,
        "started": started,
        "timeSpentSeconds": seconds,
        "author": {"displayName": author_name, "accountId": f"{author_name}-1"},
    }
