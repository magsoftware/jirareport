from __future__ import annotations

import json
from pathlib import Path

from jirareport.infrastructure.storage import (
    GcsJsonStorage,
    LocalJsonStorage,
    build_storage,
)


class FakeBlob:
    def __init__(self) -> None:
        self.payload: str | None = None
        self.content_type: str | None = None

    def upload_from_string(self, payload: str, content_type: str) -> None:
        self.payload = payload
        self.content_type = content_type


class FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob()
        self.blobs[name] = blob
        return blob


class FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        bucket = FakeBucket()
        self.buckets[name] = bucket
        return bucket


def test_local_storage_writes_pretty_json(tmp_path: Path) -> None:
    storage = LocalJsonStorage(tmp_path)

    target = storage.write_json("raw/daily/report.json", {"hello": "world"})

    saved = (tmp_path / "raw/daily/report.json").read_text(encoding="utf-8")
    assert Path(target).exists()
    assert json.loads(saved) == {"hello": "world"}


def test_gcs_storage_uploads_json_to_bucket() -> None:
    client = FakeGcsClient()
    storage = GcsJsonStorage("bucket-name", "prefix", client_factory=lambda: client)

    target = storage.write_json("raw/daily/report.json", {"hello": "world"})

    blob = client.buckets["bucket-name"].blobs["prefix/raw/daily/report.json"]
    assert json.loads(blob.payload or "{}") == {"hello": "world"}
    assert blob.content_type == "application/json"
    assert target == "gs://bucket-name/prefix/raw/daily/report.json"


def test_build_storage_returns_local_backend(tmp_path: Path) -> None:
    storage = build_storage("local", tmp_path, None, "ignored")

    result = storage.write_json("derived/monthly/report.json", {"ok": True})

    assert Path(result).exists()
