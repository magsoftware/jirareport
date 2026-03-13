from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

import yaml
from dotenv import load_dotenv

from jirareport.domain.models import JiraSpace

StorageBackend = Literal["gcs", "local"]


@dataclass(frozen=True)
class JiraSettings:
    """Holds shared Jira API credentials used across all configured spaces."""

    base_url: str
    email: str
    api_token: str


@dataclass(frozen=True)
class StorageSettings:
    """Holds configuration for the selected report storage backend."""

    backend: StorageBackend
    local_output_dir: Path
    bucket_name: str | None
    bucket_prefix: str


@dataclass(frozen=True)
class SheetsSettings:
    """Holds global Google Sheets publishing configuration."""

    enabled: bool
    title_prefix: str


@dataclass(frozen=True)
class BigQuerySettings:
    """Holds BigQuery reporting configuration."""

    enabled: bool
    project_id: str | None
    dataset: str | None
    table: str


@dataclass(frozen=True)
class ConfiguredSpace:
    """Represents one configured reporting space and its adapter settings."""

    space: JiraSpace
    board_id: int | None = None
    google_sheets_ids: tuple[tuple[int, str], ...] = ()

    def google_sheets_id_map(self) -> dict[int, str]:
        """Returns configured spreadsheet IDs keyed by reporting year."""
        return dict(self.google_sheets_ids)


@dataclass(frozen=True)
class AppSettings:
    """Represents the full application configuration."""

    jira: JiraSettings
    storage: StorageSettings
    sheets: SheetsSettings
    bigquery: BigQuerySettings
    timezone_name: str
    configured_spaces: tuple[ConfiguredSpace, ...]


def load_settings() -> AppSettings:
    """Loads and validates application settings from the environment."""
    load_dotenv()
    jira = JiraSettings(
        base_url=_required_env("JIRA_BASE_URL").rstrip("/"),
        email=_required_env("JIRA_EMAIL"),
        api_token=_required_env("JIRA_API_TOKEN"),
    )
    configured_spaces = _load_configured_spaces()
    backend = _storage_backend_from_env()
    storage = StorageSettings(
        backend=backend,
        local_output_dir=Path(os.getenv("REPORT_OUTPUT_DIR", "reports")),
        bucket_name=_bucket_name_for_backend(backend),
        bucket_prefix=os.getenv("GCS_BUCKET_PREFIX", "jirareport"),
    )
    sheets = SheetsSettings(
        enabled=_sheets_enabled_from_env(configured_spaces),
        title_prefix=os.getenv("GOOGLE_SHEETS_TITLE_PREFIX", "Jira Worklog Analytics"),
    )
    bigquery = BigQuerySettings(
        enabled=_bigquery_enabled_from_env(),
        project_id=os.getenv("BIGQUERY_PROJECT_ID"),
        dataset=os.getenv("BIGQUERY_DATASET"),
        table=os.getenv("BIGQUERY_TABLE", "worklogs"),
    )
    timezone_name = os.getenv("REPORT_TIMEZONE", "Europe/Warsaw")
    return AppSettings(
        jira=jira,
        storage=storage,
        sheets=sheets,
        bigquery=bigquery,
        timezone_name=timezone_name,
        configured_spaces=configured_spaces,
    )


def _required_env(name: str) -> str:
    """Returns a required environment variable or raises an error."""
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _storage_backend_from_env() -> StorageBackend:
    """Determines the storage backend from configuration."""
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


def _load_configured_spaces() -> tuple[ConfiguredSpace, ...]:
    """Loads configured reporting spaces from the YAML configuration file."""
    config_path = Path(os.getenv("JIRA_SPACES_CONFIG_PATH", "config/spaces.yaml"))
    payload = _load_yaml_mapping(config_path)
    raw_spaces = payload.get("spaces")
    if not isinstance(raw_spaces, list) or not raw_spaces:
        raise ValueError("Spaces configuration must define a non-empty 'spaces' list.")
    spaces = tuple(_parse_configured_space(item) for item in raw_spaces)
    _validate_unique_space_values(spaces)
    return spaces


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    """Loads a YAML file and validates that it contains a top-level mapping."""
    if not path.exists():
        raise ValueError(f"Missing spaces configuration file: {path}")
    with path.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Spaces configuration must be a YAML mapping.")
    return cast(dict[str, object], payload)


def _parse_configured_space(raw: object) -> ConfiguredSpace:
    """Parses one configured reporting space from YAML data."""
    if not isinstance(raw, Mapping):
        raise ValueError("Each space configuration entry must be a mapping.")
    key = _required_mapping_string(raw, "key")
    name = _required_mapping_string(raw, "name")
    slug = _required_mapping_string(raw, "slug")
    board_id = _optional_mapping_int(raw, "board_id")
    google_sheets_ids = _parse_sheet_ids(raw.get("google_sheets_ids"))
    return ConfiguredSpace(
        space=JiraSpace(
            key=key,
            name=name,
            slug=slug,
        ),
        board_id=board_id,
        google_sheets_ids=google_sheets_ids,
    )


def _required_mapping_string(raw: Mapping[str, object], key: str) -> str:
    """Returns a required non-empty string from a config mapping."""
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        message = f"Space configuration field '{key}' must be a non-empty string."
        raise ValueError(message)
    return value.strip()


def _optional_mapping_int(raw: Mapping[str, object], key: str) -> int | None:
    """Returns an optional integer from a config mapping."""
    value = raw.get(key)
    if value in {None, ""}:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Space configuration field '{key}' must be an integer.")
    return value


def _parse_sheet_ids(raw: object) -> tuple[tuple[int, str], ...]:
    """Parses per-year spreadsheet IDs from a config mapping."""
    if raw is None or raw == "":
        return ()
    if not isinstance(raw, Mapping):
        message = "'google_sheets_ids' must be a mapping of year to spreadsheet ID."
        raise ValueError(message)
    result: list[tuple[int, str]] = []
    for year, spreadsheet_id in raw.items():
        if not isinstance(year, int):
            raise ValueError("Google Sheets year keys must be integers.")
        if not isinstance(spreadsheet_id, str) or not spreadsheet_id.strip():
            raise ValueError("Google Sheets spreadsheet IDs must be non-empty strings.")
        result.append((year, spreadsheet_id.strip()))
    return tuple(sorted(result))


def _validate_unique_space_values(spaces: tuple[ConfiguredSpace, ...]) -> None:
    """Validates that configured spaces do not reuse key or slug values."""
    _validate_unique_attribute(spaces, "key")
    _validate_unique_attribute(spaces, "slug")


def _validate_unique_attribute(
    spaces: tuple[ConfiguredSpace, ...],
    attribute: str,
) -> None:
    """Ensures one string attribute remains unique across configured spaces."""
    seen: set[str] = set()
    for configured_space in spaces:
        value = getattr(configured_space.space, attribute)
        if value in seen:
            raise ValueError(f"Duplicate Jira space {attribute}: {value}")
        seen.add(value)


def _sheets_enabled_from_env(configured_spaces: tuple[ConfiguredSpace, ...]) -> bool:
    """Determines whether Google Sheets publishing is enabled."""
    raw_value = os.getenv("GOOGLE_SHEETS_ENABLED")
    if raw_value in {None, ""}:
        return any(configured_space.google_sheets_ids for configured_space in configured_spaces)
    assert raw_value is not None
    normalized = raw_value.lower().strip()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Unsupported GOOGLE_SHEETS_ENABLED value: {raw_value}")


def _bigquery_enabled_from_env() -> bool:
    """Determines whether BigQuery reporting is enabled."""
    raw_value = os.getenv("BIGQUERY_ENABLED")
    if raw_value in {None, ""}:
        return bool(os.getenv("BIGQUERY_PROJECT_ID") and os.getenv("BIGQUERY_DATASET"))
    assert raw_value is not None
    normalized = raw_value.lower().strip()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Unsupported BIGQUERY_ENABLED value: {raw_value}")
