from __future__ import annotations

from pathlib import Path

import pytest

from jirareport.infrastructure.config import load_settings


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
