from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest
from requests import Session

from jirareport.domain.models import DateRange, Issue
from jirareport.infrastructure.jira_client import (
    JiraWorklogSource,
    RequestParams,
    _build_session,
    _coerce_int,
    _optional_string,
    _parse_issues,
    _parse_jira_datetime,
    _parse_worklogs,
    _payload_optional_int,
)


def test_build_session_configures_auth_headers_and_adapters() -> None:
    session = _build_session("user@example.com", "secret")

    assert isinstance(session, Session)
    assert session.headers["Accept"] == "application/json"
    assert session.auth is not None


def test_parse_issues_skips_invalid_items() -> None:
    payload = {
        "issues": [
            "bad",
            {"key": "PRJ-0", "fields": "bad"},
            {
                "key": "PRJ-1",
                "fields": {"summary": "Work item", "issuetype": {"name": "Task"}},
            },
        ]
    }

    issues = _parse_issues(payload)

    assert issues == [Issue(key="PRJ-1", summary="Work item", issue_type="Task")]


def test_parse_issues_defaults_unknown_issue_type() -> None:
    payload = {"issues": [{"key": "PRJ-1", "fields": {"summary": "Work item"}}]}

    issues = _parse_issues(payload)

    assert issues == [Issue(key="PRJ-1", summary="Work item", issue_type="Unknown")]


def test_parse_worklogs_skips_non_dict_payload_items(
    warsaw_timezone: ZoneInfo,
) -> None:
    payload = {"worklogs": ["bad"]}

    result = _parse_worklogs(
        Issue("PRJ-1", "Task", "Task"),
        payload,
        DateRange(start=date(2026, 3, 1), end=date(2026, 3, 31)),
        warsaw_timezone,
    )

    assert result == []


def test_parse_jira_datetime_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="Unsupported Jira datetime format"):
        _parse_jira_datetime("2026/03/11 10:00")


def test_optional_string_returns_none_for_empty_values() -> None:
    assert _optional_string(None) is None
    assert _optional_string("") is None
    assert _optional_string(123) == "123"


def test_request_json_rejects_non_dict_payload() -> None:
    source = JiraWorklogSource(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="secret",
        project_key="PRJ",
        timezone_name="Europe/Warsaw",
        session=_PayloadSession(["bad"]),
    )

    with pytest.raises(ValueError, match="Unexpected Jira response payload"):
        source._request_json("/rest/api/3/search/jql")


def test_search_issues_falls_back_to_short_page_without_total() -> None:
    source = JiraWorklogSource(
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token="secret",
        project_key="PRJ",
        timezone_name="Europe/Warsaw",
        session=_PayloadSession(
            [
                {
                    "issues": [
                        {
                            "key": "PRJ-1",
                            "fields": {
                                "summary": "Summary 1",
                                "issuetype": {"name": "Bug"},
                            },
                        },
                        {
                            "key": "PRJ-2",
                            "fields": {
                                "summary": "Summary 2",
                                "issuetype": {"name": "Story"},
                            },
                        },
                    ]
                }
            ]
        ),
    )

    issues = source._search_issues(
        DateRange(start=date(2026, 3, 1), end=date(2026, 3, 31))
    )

    assert [issue.key for issue in issues] == ["PRJ-1", "PRJ-2"]
    assert [issue.issue_type for issue in issues] == ["Bug", "Story"]


def test_payload_optional_int_and_coerce_int_handle_strings() -> None:
    assert _payload_optional_int({"total": "123"}, "total") == 123
    assert _payload_optional_int({"total": "x"}, "total") is None
    assert _coerce_int("42") == 42
    assert _coerce_int(object()) == 0


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


class _PayloadSession:
    def __init__(self, payloads: list[object]) -> None:
        self._payloads = list(payloads)

    def get(
        self,
        url: str,
        params: RequestParams | None = None,
        timeout: int = 30,
    ) -> _Response:
        return _Response(self._payloads.pop(0))
