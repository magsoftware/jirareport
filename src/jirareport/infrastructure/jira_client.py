from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Protocol, cast
from zoneinfo import ZoneInfo

import requests
from loguru import logger
from requests.adapters import HTTPAdapter
from requests.auth import HTTPBasicAuth
from urllib3.util.retry import Retry

from jirareport.domain.models import DateRange, Issue, WorklogEntry
from jirareport.domain.ports import WorklogSource

RequestParamScalar = str | bytes | int | float
RequestParamValue = RequestParamScalar | Iterable[RequestParamScalar] | None
RequestParams = Mapping[str, RequestParamValue]


class ResponseProtocol(Protocol):
    def raise_for_status(self) -> None:
        """Raises an exception when the response is unsuccessful."""

    def json(self) -> object:
        """Returns the JSON-decoded payload."""


class SessionProtocol(Protocol):
    def get(
        self,
        url: str,
        params: RequestParams | None = None,
        timeout: int = 30,
    ) -> ResponseProtocol:
        """Performs a GET request."""


class JiraWorklogSource(WorklogSource):
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        timezone_name: str,
        session: SessionProtocol | None = None,
    ) -> None:
        self._base_url = base_url
        self._project_key = project_key
        self._timezone = ZoneInfo(timezone_name)
        self._session = session or _build_session(email, api_token)

    def fetch_worklogs(self, window: DateRange) -> list[WorklogEntry]:
        worklogs: list[WorklogEntry] = []
        for issue in self._search_issues(window):
            issue_worklogs = self._fetch_issue_worklogs(issue, window)
            worklogs.extend(issue_worklogs)
        return worklogs

    def _search_issues(self, window: DateRange) -> list[Issue]:
        issues: list[Issue] = []
        start_at = 0
        next_page_token: str | None = None
        while True:
            payload = self._search_issue_page(window, start_at, next_page_token)
            page_issues = _parse_issues(payload)
            issues.extend(page_issues)
            issue_count = len(page_issues)
            next_page_token = _payload_string(payload, "nextPageToken")
            if next_page_token:
                continue
            if _payload_bool(payload, "isLast"):
                return issues
            start_at += issue_count
            total = _payload_optional_int(payload, "total")
            if total is not None and start_at >= total:
                return issues
            if issue_count < 100:
                return issues

    def _search_issue_page(
        self,
        window: DateRange,
        start_at: int,
        next_page_token: str | None = None,
    ) -> Mapping[str, object]:
        jql = _worklog_window_jql(self._project_key, window)
        params: dict[str, RequestParamValue] = {
            "jql": jql,
            "maxResults": 100,
            "fields": "summary",
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token
        else:
            params["startAt"] = start_at
        logger.debug("Jira issue search JQL: {}", jql)
        return self._request_json("/rest/api/3/search/jql", params=params)

    def _fetch_issue_worklogs(
        self,
        issue: Issue,
        window: DateRange,
    ) -> list[WorklogEntry]:
        worklogs: list[WorklogEntry] = []
        start_at = 0
        while True:
            payload = self._request_json(
                f"/rest/api/3/issue/{issue.key}/worklog",
                params={"startAt": start_at, "maxResults": 100},
            )
            entries = _parse_worklogs(issue, payload, window, self._timezone)
            worklogs.extend(entries)
            start_at += len(_payload_list(payload, "worklogs"))
            if start_at >= _payload_int(payload, "total"):
                return worklogs

    def _request_json(
        self,
        path: str,
        params: RequestParams | None = None,
    ) -> Mapping[str, object]:
        response = self._session.get(
            f"{self._base_url}{path}",
            params=params,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Unexpected Jira response payload.")
        return payload


def _build_session(email: str, api_token: str) -> SessionProtocol:
    session = requests.Session()
    session.auth = HTTPBasicAuth(email, api_token)
    session.headers.update({"Accept": "application/json"})
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return cast(SessionProtocol, session)


def _worklog_window_jql(project_key: str, window: DateRange) -> str:
    return (
        f'project = "{project_key}" '
        f'AND worklogDate >= "{window.start.isoformat()}" '
        f'AND worklogDate <= "{window.end.isoformat()}" '
        "ORDER BY created DESC"
    )


def _parse_issues(payload: Mapping[str, object]) -> list[Issue]:
    result: list[Issue] = []
    for item in _payload_list(payload, "issues"):
        if not isinstance(item, Mapping):
            continue
        fields = item.get("fields") or {}
        if not isinstance(fields, Mapping):
            continue
        result.append(
            Issue(
                key=str(item["key"]),
                summary=str(fields.get("summary") or ""),
            )
        )
    return result


def _parse_worklogs(
    issue: Issue,
    payload: Mapping[str, object],
    window: DateRange,
    timezone: ZoneInfo,
) -> list[WorklogEntry]:
    entries: list[WorklogEntry] = []
    for item in _payload_list(payload, "worklogs"):
        if not isinstance(item, Mapping):
            continue
        entry = _to_worklog_entry(issue, item, timezone)
        if window.contains(entry.started_at.date()):
            entries.append(entry)
    return entries


def _to_worklog_entry(
    issue: Issue,
    worklog: Mapping[str, object],
    timezone: ZoneInfo,
) -> WorklogEntry:
    started_at = _parse_jira_datetime(str(worklog["started"])).astimezone(timezone)
    duration_seconds = _coerce_int(worklog.get("timeSpentSeconds", 0))
    author = worklog.get("author") or {}
    author_payload = author if isinstance(author, Mapping) else {}
    ended_at = started_at + timedelta(seconds=duration_seconds)
    return WorklogEntry(
        worklog_id=str(worklog["id"]),
        issue_key=issue.key,
        issue_summary=issue.summary,
        author_name=str(author_payload.get("displayName") or "Unknown"),
        author_account_id=_optional_string(author_payload.get("accountId")),
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
    )


def _parse_jira_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported Jira datetime format: {value}")


def _optional_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _payload_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _payload_int(payload: Mapping[str, object], key: str) -> int:
    return _coerce_int(payload.get(key, 0))


def _payload_optional_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _payload_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else False


def _payload_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _coerce_int(value: object) -> int:
    return int(value) if isinstance(value, int | str) else 0
