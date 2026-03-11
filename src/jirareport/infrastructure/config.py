from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from dotenv import load_dotenv

StorageBackend = Literal["gcs", "local"]


@dataclass(frozen=True)
class JiraSettings:
    base_url: str
    email: str
    api_token: str
    project_key: str


@dataclass(frozen=True)
class StorageSettings:
    backend: StorageBackend
    local_output_dir: Path
    bucket_name: str | None
    bucket_prefix: str


@dataclass(frozen=True)
class AppSettings:
    jira: JiraSettings
    storage: StorageSettings
    timezone_name: str


def load_settings() -> AppSettings:
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
    timezone_name = os.getenv("REPORT_TIMEZONE", "Europe/Warsaw")
    return AppSettings(jira=jira, storage=storage, timezone_name=timezone_name)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _storage_backend_from_env() -> StorageBackend:
    backend_value = os.getenv("REPORT_STORAGE_BACKEND")
    if backend_value in {None, ""}:
        return "gcs" if os.getenv("GCS_BUCKET_NAME") else "local"
    if backend_value not in {"gcs", "local"}:
        raise ValueError(f"Unsupported storage backend: {backend_value}")
    return cast(StorageBackend, backend_value)


def _bucket_name_for_backend(backend: StorageBackend) -> str | None:
    if backend == "local":
        return os.getenv("GCS_BUCKET_NAME")
    return _required_env("GCS_BUCKET_NAME")
