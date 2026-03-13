from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from jirareport.domain.ports import (
    CuratedDatasetStorage,
    JsonObject,
    JsonReportStorage,
)


class GcsBlobProtocol(Protocol):
    """Describes the subset of blob behavior used by the storage adapters."""

    def upload_from_string(self, data: str | bytes, content_type: str) -> None:
        """Uploads raw bytes or text to the blob."""

    def download_as_bytes(self) -> bytes:
        """Downloads raw blob data."""


class GcsBucketProtocol(Protocol):
    """Describes the subset of bucket behavior used by the storage adapters."""

    def blob(self, blob_name: str) -> GcsBlobProtocol:
        """Returns a handle to one blob."""


class GcsClientProtocol(Protocol):
    """Describes the subset of GCS client behavior used by the adapters."""

    def bucket(self, bucket_name: str) -> GcsBucketProtocol:
        """Returns a handle to one bucket."""


JsonPayload = JsonObject
GcsClientFactory = Callable[[], GcsClientProtocol]
PARQUET_CONTENT_TYPE = "application/vnd.apache.parquet"


class LocalJsonReportStorage:
    """Stores report payloads as JSON files on the local filesystem."""

    def __init__(self, root_dir: Path) -> None:
        """Initializes the local storage backend."""
        self._root_dir = root_dir

    def write_json(self, path: str, payload: JsonPayload) -> str:
        """Writes a JSON payload to the configured local output directory."""
        target = self._root_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_to_json(payload), encoding="utf-8")
        return str(target)


class LocalCuratedDatasetStorage:
    """Stores curated binary datasets on the local filesystem."""

    def __init__(self, root_dir: Path) -> None:
        """Initializes the local curated dataset backend."""
        self._root_dir = root_dir

    def write_parquet(self, path: str, payload: bytes) -> str:
        """Writes a Parquet payload to the configured local output directory."""
        target = self._root_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return str(target)

    def read_bytes(self, path: str) -> bytes:
        """Reads a binary payload from the configured local output directory."""
        return (self._root_dir / path).read_bytes()


class GcsJsonReportStorage:
    """Stores report payloads as JSON objects in Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str,
        bucket_prefix: str,
        client_factory: GcsClientFactory | None = None,
    ) -> None:
        """Initializes the GCS storage backend."""
        self._bucket_name = bucket_name
        self._bucket_prefix = bucket_prefix.strip("/")
        self._client_factory = client_factory or _default_gcs_client_factory

    def write_json(self, path: str, payload: JsonPayload) -> str:
        """Writes a JSON payload to the configured GCS bucket."""
        client = self._client_factory()
        bucket = client.bucket(self._bucket_name)
        blob_name = _blob_name(self._bucket_prefix, path)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(_to_json(payload), content_type="application/json")
        return f"gs://{self._bucket_name}/{blob_name}"


class GcsCuratedDatasetStorage:
    """Stores curated binary datasets in Google Cloud Storage."""

    def __init__(
        self,
        bucket_name: str,
        bucket_prefix: str,
        client_factory: GcsClientFactory | None = None,
    ) -> None:
        """Initializes the GCS curated dataset backend."""
        self._bucket_name = bucket_name
        self._bucket_prefix = bucket_prefix.strip("/")
        self._client_factory = client_factory or _default_gcs_client_factory

    def write_parquet(self, path: str, payload: bytes) -> str:
        """Writes a Parquet payload to the configured GCS bucket."""
        client = self._client_factory()
        bucket = client.bucket(self._bucket_name)
        blob_name = _blob_name(self._bucket_prefix, path)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(payload, content_type=PARQUET_CONTENT_TYPE)
        return f"gs://{self._bucket_name}/{blob_name}"

    def read_bytes(self, path: str) -> bytes:
        """Reads a binary payload from the configured GCS bucket."""
        client = self._client_factory()
        bucket = client.bucket(self._bucket_name)
        blob_name = _blob_name(self._bucket_prefix, path)
        blob = bucket.blob(blob_name)
        return bytes(blob.download_as_bytes())


def build_json_report_storage(
    backend: str,
    root_dir: Path,
    bucket_name: str | None,
    prefix: str,
) -> JsonReportStorage:
    """Builds the configured storage backend for JSON report persistence."""
    if backend == "gcs":
        if bucket_name is None:
            raise ValueError("GCS bucket name is required for gcs backend.")
        return GcsJsonReportStorage(bucket_name=bucket_name, bucket_prefix=prefix)
    return LocalJsonReportStorage(root_dir=root_dir)


def build_curated_dataset_storage(
    backend: str,
    root_dir: Path,
    bucket_name: str | None,
    prefix: str,
) -> CuratedDatasetStorage:
    """Builds the configured storage backend for curated binary datasets."""
    if backend == "gcs":
        if bucket_name is None:
            raise ValueError("GCS bucket name is required for gcs backend.")
        return GcsCuratedDatasetStorage(
            bucket_name=bucket_name,
            bucket_prefix=prefix,
        )
    return LocalCuratedDatasetStorage(root_dir=root_dir)


def _to_json(payload: JsonPayload) -> str:
    """Serializes a payload to pretty-printed JSON."""
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _blob_name(prefix: str, path: str) -> str:
    """Builds the target object name for the GCS backend."""
    return f"{prefix}/{path}" if prefix else path


def _default_gcs_client_factory() -> GcsClientProtocol:
    """Builds the default Google Cloud Storage client."""
    import google.cloud.storage as storage

    return cast(GcsClientProtocol, storage.Client())
