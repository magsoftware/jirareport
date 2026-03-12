from __future__ import annotations

import os
from pathlib import Path

import pytest

from jirareport.infrastructure.config import load_settings


@pytest.fixture(autouse=True)
def clear_google_sheets_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removes local Google Sheets settings so tests stay environment-independent."""
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "")
    monkeypatch.delenv("JIRA_SPACES_CONFIG_PATH", raising=False)
    for name in tuple(os.environ):
        if name.startswith("GOOGLE_SHEETS_ID_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def spaces_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Creates a temporary spaces.yaml config used by settings tests."""
    path = tmp_path / "spaces.yaml"
    path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(path))
    return path


def test_load_settings_defaults_to_gcs_when_bucket_present(
    monkeypatch: pytest.MonkeyPatch,
    spaces_config: Path,
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
    assert settings.sheets.title_prefix == "Jira Worklog Analytics"
    assert settings.spaces[0].key == "LA004832"
    assert settings.spaces[0].slug == "click-price"


def test_load_settings_supports_local_storage(
    monkeypatch: pytest.MonkeyPatch,
    spaces_config: Path,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("REPORT_STORAGE_BACKEND", "local")
    monkeypatch.setenv("REPORT_OUTPUT_DIR", "artifacts")

    settings = load_settings()

    assert settings.storage.backend == "local"
    assert settings.storage.local_output_dir == Path("artifacts")


def test_load_settings_enables_google_sheets_when_space_has_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids:",
                "      2026: sheet-2026",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    settings = load_settings()

    assert settings.sheets.enabled is True
    assert settings.spaces[0].safe_google_sheets_ids == {2026: "sheet-2026"}


def test_load_settings_rejects_unknown_google_sheets_enabled_value(
    monkeypatch: pytest.MonkeyPatch,
    spaces_config: Path,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "maybe")

    with pytest.raises(ValueError, match="Unsupported GOOGLE_SHEETS_ENABLED value"):
        load_settings()


def test_load_settings_rejects_unknown_storage_backend(
    monkeypatch: pytest.MonkeyPatch,
    spaces_config: Path,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("REPORT_STORAGE_BACKEND", "invalid")

    with pytest.raises(ValueError, match="Unsupported storage backend"):
        load_settings()


def test_load_settings_requires_jira_configuration(
    monkeypatch: pytest.MonkeyPatch,
    spaces_config: Path,
) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "")
    monkeypatch.setenv("JIRA_EMAIL", "")
    monkeypatch.setenv("JIRA_API_TOKEN", "")

    with pytest.raises(ValueError, match="Missing required environment variable"):
        load_settings()


def test_load_settings_rejects_missing_spaces_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(ValueError, match="Missing spaces configuration file"):
        load_settings()


def test_load_settings_rejects_non_mapping_spaces_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text("- invalid\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(ValueError, match="Spaces configuration must be a YAML mapping"):
        load_settings()


def test_load_settings_rejects_empty_spaces_list(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text("spaces: []\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(
        ValueError,
        match="Spaces configuration must define a non-empty 'spaces' list",
    ):
        load_settings()


def test_load_settings_rejects_space_entry_that_is_not_a_mapping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text("spaces:\n  - invalid\n", encoding="utf-8")
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(
        ValueError,
        match="Each space configuration entry must be a mapping",
    ):
        load_settings()


@pytest.mark.parametrize("field", ["key", "name", "slug"])
def test_load_settings_rejects_blank_required_space_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
) -> None:
    values = {
        "key": "LA004832",
        "name": "Click Price",
        "slug": "click-price",
    }
    values[field] = ""
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                f"  - key: '{values['key']}'",
                f"    name: '{values['name']}'",
                f"    slug: '{values['slug']}'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(
        ValueError,
        match=f"Space configuration field '{field}' must be a non-empty string",
    ):
        load_settings()


def test_load_settings_rejects_non_integer_board_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    board_id: bad",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(
        ValueError,
        match="Space configuration field 'board_id' must be an integer",
    ):
        load_settings()


def test_load_settings_rejects_invalid_google_sheets_ids_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids: bad",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(ValueError, match="'google_sheets_ids' must be a mapping"):
        load_settings()


def test_load_settings_rejects_non_integer_google_sheets_year_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids:",
                "      bad: sheet-2026",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(ValueError, match="Google Sheets year keys must be integers"):
        load_settings()


def test_load_settings_rejects_blank_google_sheets_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids:",
                "      2026: ''",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(
        ValueError,
        match="Google Sheets spreadsheet IDs must be non-empty strings",
    ):
        load_settings()


def test_load_settings_rejects_duplicate_space_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "  - key: LA004832",
                "    name: Data Fixer",
                "    slug: data-fixer",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")

    with pytest.raises(ValueError, match="Duplicate Jira space key: LA004832"):
        load_settings()


def test_load_settings_supports_explicit_google_sheets_disable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "spaces.yaml"
    config_path.write_text(
        "\n".join(
            [
                "spaces:",
                "  - key: LA004832",
                "    name: Click Price",
                "    slug: click-price",
                "    google_sheets_ids:",
                "      2026: sheet-2026",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JIRA_SPACES_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "secret")
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "off")

    settings = load_settings()

    assert settings.sheets.enabled is False
