from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest

from jirareport.infrastructure import storage


def test_storage_builders_reject_missing_bucket_for_gcs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="GCS bucket name is required"):
        storage.build_json_report_storage("gcs", tmp_path, None, "prefix")
    with pytest.raises(ValueError, match="GCS bucket name is required"):
        storage.build_curated_dataset_storage("gcs", tmp_path, None, "prefix")


def test_default_gcs_client_factory_uses_google_storage_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_storage_module = cast(Any, ModuleType("storage"))
    fake_storage_module.Client = lambda: "fake-client"
    fake_cloud_module = cast(Any, ModuleType("google.cloud"))
    fake_cloud_module.storage = fake_storage_module
    fake_google_module = cast(Any, ModuleType("google"))
    fake_google_module.cloud = fake_cloud_module
    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.cloud", fake_cloud_module)
    monkeypatch.setitem(sys.modules, "google.cloud.storage", fake_storage_module)

    client = storage._default_gcs_client_factory()

    assert client == "fake-client"
