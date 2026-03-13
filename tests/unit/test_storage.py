from __future__ import annotations

import json
from pathlib import Path

from jirareport.infrastructure.storage import (
    PARQUET_CONTENT_TYPE,
    GcsCuratedDatasetStorage,
    GcsJsonReportStorage,
    LocalCuratedDatasetStorage,
    LocalJsonReportStorage,
    build_curated_dataset_storage,
    build_json_report_storage,
)


class FakeBlob:
    def __init__(self) -> None:
        self.payload: str | bytes | None = None
        self.content_type: str | None = None

    def upload_from_string(self, payload: str | bytes, content_type: str) -> None:
        self.payload = payload
        self.content_type = content_type

    def download_as_bytes(self) -> bytes:
        assert isinstance(self.payload, bytes)
        return self.payload


class FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        blob = self.blobs.get(name)
        if blob is None:
            blob = FakeBlob()
            self.blobs[name] = blob
        return blob


class FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        bucket = self.buckets.get(name)
        if bucket is None:
            bucket = FakeBucket()
            self.buckets[name] = bucket
        return bucket


def test_local_storage_writes_pretty_json(tmp_path: Path) -> None:
    storage = LocalJsonReportStorage(tmp_path)

    target = storage.write_json("raw/daily/report.json", {"hello": "world"})

    saved = (tmp_path / "raw/daily/report.json").read_text(encoding="utf-8")
    assert Path(target).exists()
    assert json.loads(saved) == {"hello": "world"}


def test_gcs_storage_uploads_json_to_bucket() -> None:
    client = FakeGcsClient()
    storage = GcsJsonReportStorage(
        "bucket-name",
        "prefix",
        client_factory=lambda: client,
    )

    target = storage.write_json("raw/daily/report.json", {"hello": "world"})

    blob = client.buckets["bucket-name"].blobs["prefix/raw/daily/report.json"]
    assert json.loads(blob.payload or "{}") == {"hello": "world"}
    assert blob.content_type == "application/json"
    assert target == "gs://bucket-name/prefix/raw/daily/report.json"


def test_build_json_report_storage_returns_local_backend(tmp_path: Path) -> None:
    storage = build_json_report_storage("local", tmp_path, None, "ignored")

    result = storage.write_json("derived/monthly/report.json", {"ok": True})

    assert Path(result).exists()


def test_local_storage_writes_parquet_bytes(tmp_path: Path) -> None:
    storage = LocalCuratedDatasetStorage(tmp_path)

    target = storage.write_parquet("curated/worklogs.parquet", b"PAR1")

    assert (tmp_path / "curated/worklogs.parquet").read_bytes() == b"PAR1"
    assert Path(target).exists()
    assert storage.read_bytes("curated/worklogs.parquet") == b"PAR1"


def test_gcs_storage_uploads_parquet_to_bucket() -> None:
    client = FakeGcsClient()
    storage = GcsCuratedDatasetStorage(
        "bucket-name",
        "prefix",
        client_factory=lambda: client,
    )

    target = storage.write_parquet("curated/worklogs.parquet", b"PAR1")

    blob = client.buckets["bucket-name"].blobs["prefix/curated/worklogs.parquet"]
    assert blob.payload == b"PAR1"
    assert blob.content_type == PARQUET_CONTENT_TYPE
    assert target == "gs://bucket-name/prefix/curated/worklogs.parquet"


def test_gcs_storage_reads_bytes_from_bucket() -> None:
    client = FakeGcsClient()
    storage = GcsCuratedDatasetStorage(
        "bucket-name",
        "prefix",
        client_factory=lambda: client,
    )
    storage.write_parquet("curated/worklogs.parquet", b"PAR1")

    payload = storage.read_bytes("curated/worklogs.parquet")

    assert payload == b"PAR1"


def test_build_curated_dataset_storage_returns_local_backend(tmp_path: Path) -> None:
    storage = build_curated_dataset_storage("local", tmp_path, None, "ignored")

    target = storage.write_parquet("curated/worklogs.parquet", b"PAR1")

    assert Path(target).exists()
