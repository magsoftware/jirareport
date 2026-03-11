from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jirareport.domain.ports import ReportStorage

JsonPayload = dict[str, Any]
GcsClientFactory = Callable[[], Any]


class LocalJsonStorage:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def write_json(self, path: str, payload: JsonPayload) -> str:
        target = self._root_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_to_json(payload), encoding="utf-8")
        return str(target)


class GcsJsonStorage:
    def __init__(
        self,
        bucket_name: str,
        bucket_prefix: str,
        client_factory: GcsClientFactory | None = None,
    ) -> None:
        self._bucket_name = bucket_name
        self._bucket_prefix = bucket_prefix.strip("/")
        self._client_factory = client_factory or _default_gcs_client_factory

    def write_json(self, path: str, payload: JsonPayload) -> str:
        client = self._client_factory()
        bucket = client.bucket(self._bucket_name)
        blob_name = _blob_name(self._bucket_prefix, path)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(_to_json(payload), content_type="application/json")
        return f"gs://{self._bucket_name}/{blob_name}"


def build_storage(
    backend: str,
    root_dir: Path,
    bucket_name: str | None,
    prefix: str,
) -> ReportStorage:
    if backend == "gcs":
        if bucket_name is None:
            raise ValueError("GCS bucket name is required for gcs backend.")
        return GcsJsonStorage(bucket_name=bucket_name, bucket_prefix=prefix)
    return LocalJsonStorage(root_dir=root_dir)


def _to_json(payload: JsonPayload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _blob_name(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def _default_gcs_client_factory() -> Any:
    from google.cloud import storage

    return storage.Client()
