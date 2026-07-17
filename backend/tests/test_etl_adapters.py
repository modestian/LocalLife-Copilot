from pathlib import Path
from uuid import UUID

import pytest

from app.etl.adapters import LocalSourceStorage, OpenSearchProjection
from app.etl.lifecycle import LifecycleError, projection_id
from app.etl.models import ChunkRecord

VERSION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b123")


class FakeOpenSearch:
    def __init__(self) -> None:
        self.count_value = 0
        self.deleted_value = 0
        self.count_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def count(self, **kwargs):
        self.count_calls.append(kwargs)
        return {"count": self.count_value}

    def delete_by_query(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {"deleted": self.deleted_value}


def chunk(number: int = 0) -> ChunkRecord:
    return ChunkRecord(
        document_version_id=VERSION_ID,
        chunk_no=number,
        content="环境安静",
        content_hash="a" * 64,
        token_count=4,
        metadata={
            "source_key": "reviews/store.txt",
            "knowledge_base_id": "kb-1",
            "merchant_id": "merchant-1",
            "business_status": "OPEN",
            "valid_to": "2026-12-31T23:59:59Z",
        },
    )


def test_local_source_storage_opens_files_inside_configured_root(tmp_path: Path) -> None:
    source = tmp_path / "nested" / "sample.txt"
    source.parent.mkdir()
    source.write_bytes("环境安静".encode())

    with LocalSourceStorage(tmp_path).open("nested/sample.txt") as stream:
        assert stream.read() == "环境安静".encode()


@pytest.mark.parametrize("uri", ["../outside.txt", "https://example.com/source.txt"])
def test_local_source_storage_rejects_unsafe_or_unsupported_uris(tmp_path: Path, uri: str) -> None:
    with pytest.raises(LifecycleError) as captured:
        LocalSourceStorage(tmp_path).open(uri)

    assert captured.value.code in {"SOURCE_PATH_FORBIDDEN", "SOURCE_URI_UNSUPPORTED"}


def test_opensearch_projection_uses_stable_ids_for_idempotent_upsert(monkeypatch) -> None:
    client = FakeOpenSearch()
    captured: list[dict[str, object]] = []

    def fake_bulk(_client, actions, **kwargs):
        assert _client is client
        assert kwargs == {"refresh": "wait_for", "raise_on_error": True}
        captured.extend(actions)
        return len(actions), []

    monkeypatch.setattr("app.etl.adapters.bulk", fake_bulk)
    projection = OpenSearchProjection(client, "knowledge-index")

    projection.upsert(VERSION_ID, [chunk()])
    projection.upsert(VERSION_ID, [chunk()])

    assert [action["_id"] for action in captured] == [
        projection_id(VERSION_ID, 0),
        projection_id(VERSION_ID, 0),
    ]
    assert captured[0]["_source"]["document_version_id"] == str(VERSION_ID)
    assert captured[0]["_source"]["source_key"] == "reviews/store.txt"
    assert captured[0]["_source"]["knowledge_base_id"] == "kb-1"
    assert captured[0]["_source"]["business_status"] == "OPEN"
    assert captured[0]["_source"]["valid_to"] == "2026-12-31T23:59:59Z"


def test_opensearch_projection_counts_and_deletes_one_document_version() -> None:
    client = FakeOpenSearch()
    client.count_value = 3
    client.deleted_value = 3
    projection = OpenSearchProjection(client, "knowledge-index")

    assert projection.count(VERSION_ID) == 3
    assert projection.delete(VERSION_ID) == 3

    expected_query = {"query": {"term": {"document_version_id": str(VERSION_ID)}}}
    assert client.count_calls == [{"index": "knowledge-index", "body": expected_query}]
    assert client.delete_calls == [
        {
            "index": "knowledge-index",
            "body": expected_query,
            "conflicts": "proceed",
            "refresh": True,
        }
    ]
