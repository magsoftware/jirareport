from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv

StorageBackend = Literal["gcs", "local"]


@dataclass(frozen=True)
class JiraSettings:
    """Holds Jira API configuration required by the report source."""

    base_url: str
    email: str
    api_token: str
    project_key: str


@dataclass(frozen=True)
class StorageSettings:
    """Holds configuration for the selected report storage backend."""

    backend: StorageBackend
    local_output_dir: Path
    bucket_name: str | None
    bucket_prefix: str


@dataclass(frozen=True)
class SheetsSettings:
    """Holds configuration for yearly Google Sheets publishing."""

    enabled: bool
    spreadsheet_ids: dict[int, str]

    def spreadsheet_id_for_year(self, year: int) -> str:
        """Returns the configured spreadsheet ID for the requested year."""
        try:
            return self.spreadsheet_ids[year]
        except KeyError as exc:
            message = f"Missing Google Sheets spreadsheet ID for year {year}."
            raise ValueError(message) from exc


@dataclass(frozen=True)
class AppSettings:
    """Represents the full application configuration."""

    jira: JiraSettings
    storage: StorageSettings
    sheets: SheetsSettings
    timezone_name: str


def load_settings() -> AppSettings:
    """Loads and validates application settings from the environment."""
    load_dotenv()
    jira = JiraSettings(
        base_url=_required_env("JIRA_BASE_URL").rstrip("/"),
        email=_required_env("JIRA_EMAIL"),
        api_token=_required_env("JIRA_API_TOKEN"),
        project_key=os.getenv("JIRA_PROJECT_KEY", "LA004832"),
    )
    backend = _storage_backend_from_env()
    storage = StorageSettings(
        backend=backend,
        local_output_dir=Path(os.getenv("REPORT_OUTPUT_DIR", "reports")),
        bucket_name=_bucket_name_for_backend(backend),
        bucket_prefix=os.getenv("GCS_BUCKET_PREFIX", "jirareport"),
    )
    sheet_ids = _sheet_ids_from_env()
    sheets = SheetsSettings(
        enabled=_sheets_enabled_from_env(sheet_ids),
        spreadsheet_ids=sheet_ids,
    )
    timezone_name = os.getenv("REPORT_TIMEZONE", "Europe/Warsaw")
    return AppSettings(
        jira=jira,
        storage=storage,
        sheets=sheets,
        timezone_name=timezone_name,
    )


def _required_env(name: str) -> str:
    """Returns a required environment variable or raises an error."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _storage_backend_from_env() -> StorageBackend:
    """Determines the storage backend from configuration.

    An explicit backend wins. If no backend is provided, the function defaults
    to GCS when a bucket name is configured and otherwise falls back to local
    storage.
    """
    backend_value = os.getenv("REPORT_STORAGE_BACKEND")
    if backend_value in {None, ""}:
        return "gcs" if os.getenv("GCS_BUCKET_NAME") else "local"
    if backend_value not in {"gcs", "local"}:
        raise ValueError(f"Unsupported storage backend: {backend_value}")
    return cast(StorageBackend, backend_value)


def _bucket_name_for_backend(backend: StorageBackend) -> str | None:
    """Returns the bucket name required by the selected storage backend."""
    if backend == "local":
        return os.getenv("GCS_BUCKET_NAME")
    return _required_env("GCS_BUCKET_NAME")


def _sheet_ids_from_env() -> dict[int, str]:
    """Loads configured yearly spreadsheet IDs from environment variables."""
    result: dict[int, str] = {}
    prefix = "GOOGLE_SHEETS_ID_"
    for name, value in os.environ.items():
        if not name.startswith(prefix) or not value:
            continue
        year = int(name.removeprefix(prefix))
        result[year] = value
    return result


def _sheets_enabled_from_env(sheet_ids: dict[int, str]) -> bool:
    """Determines whether Google Sheets publishing is enabled."""
    raw_value = os.getenv("GOOGLE_SHEETS_ENABLED")
    if raw_value in {None, ""}:
        return bool(sheet_ids)
    assert raw_value is not None
    normalized = raw_value.lower().strip()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Unsupported GOOGLE_SHEETS_ENABLED value: {raw_value}")
