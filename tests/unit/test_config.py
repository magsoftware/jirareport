from __future__ import annotations

import os
from pathlib import Path

import pytest

from jirareport.infrastructure.config import load_settings


@pytest.fixture(autouse=True)
def clear_google_sheets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removes local Google Sheets settings so tests stay environment-independent."""
    monkeypatch.delenv("GOOGLE_SHEETS_ENABLED", raising=False)
    for name in tuple(os.environ):
        if name.startswith("GOOGLE_SHEETS_ID_"):
            monkeypatch.delenv(name, raising=False)


def test_load_settings_defaults_to_gcs_when_bucket_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("GCS_BUCKET_NAME", "jira-reports")
    monkeypatch.setenv("REPORT_STORAGE_BACKEND", "")

    settings = load_settings()

    assert settings.storage.backend == "gcs"
    assert settings.storage.bucket_name == "jira-reports"
    assert settings.storage.bucket_prefix == "jirareport"
    assert settings.sheets.enabled is False
    assert settings.sheets.spreadsheet_ids == {}


def test_load_settings_supports_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("REPORT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REPORT_OUTPUT_DIR", "artifacts")

    settings = load_settings()

    assert settings.storage.backend == "local"
    assert settings.storage.local_output_dir == Path("artifacts")


def test_load_settings_enables_google_sheets_when_ids_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_SHEETS_ID_2026", "sheet-2026")

    settings = load_settings()

    assert settings.sheets.enabled is True
    assert settings.sheets.spreadsheet_ids == {2026: "sheet-2026"}


def test_load_settings_rejects_unknown_google_sheets_enabled_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "maybe")

    with pytest.raises(ValueError, match="Unsupported GOOGLE_SHEETS_ENABLED value"):
        load_settings()


def test_load_settings_rejects_unknown_storage_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("REPORT_STORAGE_BACKEND", "invalid")

    with pytest.raises(ValueError, match="Unsupported storage backend"):
        load_settings()


def test_load_settings_requires_jira_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "")
    monkeypatch.setenv("JIRA_EMAIL", "")
    monkeypatch.setenv("JIRA_API_TOKEN", "")

    with pytest.raises(ValueError, match="Missing required environment variable"):
        load_settings()
