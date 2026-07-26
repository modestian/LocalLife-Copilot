from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from app.etl.adapters import LocalSourceStorage, OpenSearchProjection, _geo_location, _is_coordinate
from app.etl.embeddings import BatchedEmbedder
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
            "chunk_id": "0190c4d2-7f20-7b31-9f75-8f6cc8e2b124",
            "source_key": "reviews/store.txt",
            "tenant_id": "tenant-1",
            "knowledge_base_id": "kb-1",
            "resource_scope": ["KNOWLEDGE_BASE:kb-1"],
            "merchant_id": "merchant-1",
            "business_status": "OPEN",
            "valid_to": "2026-12-31T23:59:59Z",
        },
    )


class FakeEmbeddingProvider:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


def projection(client: FakeOpenSearch) -> OpenSearchProjection:
    embedder = BatchedEmbedder(FakeEmbeddingProvider(), dimension=3, batch_size=2)
    return OpenSearchProjection(client, "knowledge-index", embedder, bulk_batch_size=2)


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
        assert kwargs == {
            "chunk_size": 2,
            "refresh": "wait_for",
            "raise_on_error": True,
            "raise_on_exception": True,
        }
        captured.extend(actions)
        return len(actions), []

    monkeypatch.setattr("app.etl.adapters.bulk", fake_bulk)
    search_projection = projection(client)

    search_projection.upsert(VERSION_ID, [chunk()])
    search_projection.upsert(VERSION_ID, [chunk()])

    assert [action["_id"] for action in captured] == [
        projection_id(VERSION_ID, 0),
        projection_id(VERSION_ID, 0),
    ]
    assert captured[0]["_source"]["document_version_id"] == str(VERSION_ID)
    assert captured[0]["_source"]["chunk_id"] == "0190c4d2-7f20-7b31-9f75-8f6cc8e2b124"
    assert captured[0]["_source"]["source_key"] == "reviews/store.txt"
    assert captured[0]["_source"]["tenant_id"] == "tenant-1"
    assert captured[0]["_source"]["knowledge_base_id"] == "kb-1"
    assert captured[0]["_source"]["resource_scope"] == ["KNOWLEDGE_BASE:kb-1"]
    assert captured[0]["_source"]["business_status"] == "OPEN"
    assert captured[0]["_source"]["valid_to"] == "2026-12-31T23:59:59Z"
    assert captured[0]["_source"]["content_vector"] == [0.1, 0.2, 0.3]


def test_opensearch_projection_does_not_treat_source_locator_as_geo_point() -> None:
    source = OpenSearchProjection._source(
        VERSION_ID,
        replace(chunk(), metadata={**chunk().metadata, "location": "uploads/store.md"}),
        [0.1, 0.2, 0.3],
    )

    assert "location" not in source


def test_opensearch_projection_keeps_valid_geo_point() -> None:
    source = OpenSearchProjection._source(
        VERSION_ID,
        replace(chunk(), metadata={**chunk().metadata, "location": {"lat": 31.23, "lon": 121.47}}),
        [0.1, 0.2, 0.3],
    )

    assert source["location"] == {"lat": 31.23, "lon": 121.47}


def test_opensearch_projection_counts_and_deletes_one_document_version() -> None:
    client = FakeOpenSearch()
    client.count_value = 3
    client.deleted_value = 3
    search_projection = projection(client)

    assert search_projection.count(VERSION_ID) == 3
    assert search_projection.delete(VERSION_ID) == 3

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


def test_haversine_distance_computes_correctly() -> None:
    from app.etl.merchant_reviews import _haversine_distance

    # 春熙路 → 天府广场 ≈ 1.2 km
    d = _haversine_distance(104.08, 30.66, 104.066, 30.658)
    assert 1000 < d < 2000

    # Same point → 0
    assert _haversine_distance(104.08, 30.66, 104.08, 30.66) == 0

    # Beijing → Shanghai ≈ 1068 km
    d2 = _haversine_distance(116.407, 39.904, 121.474, 31.23)
    assert 1_000_000 < d2 < 1_100_000


# ---------------------------------------------------------------------------
# _geo_location
# ---------------------------------------------------------------------------


def test_geo_location_dict_valid() -> None:
    assert _geo_location({"lat": 31.23, "lon": 121.47}) == {"lat": 31.23, "lon": 121.47}


def test_geo_location_dict_invalid_lat() -> None:
    assert _geo_location({"lat": 200, "lon": 121.47}) is None


def test_geo_location_dict_invalid_lon() -> None:
    assert _geo_location({"lat": 31.23, "lon": 200}) is None


def test_geo_location_list_valid() -> None:
    assert _geo_location([121.47, 31.23]) == [121.47, 31.23]


def test_geo_location_list_wrong_length() -> None:
    assert _geo_location([121.47]) is None


def test_geo_location_list_out_of_range() -> None:
    assert _geo_location([200, 200]) is None


def test_geo_location_string_valid() -> None:
    assert _geo_location("31.23, 121.47") == "31.23,121.47"


def test_geo_location_string_invalid_format() -> None:
    assert _geo_location("not,coord") is None


def test_geo_location_string_out_of_range() -> None:
    assert _geo_location("200, 200") is None


def test_geo_location_unsupported_types() -> None:
    assert _geo_location(None) is None
    assert _geo_location(42) is None
    assert _geo_location(True) is None


# ---------------------------------------------------------------------------
# _is_coordinate
# ---------------------------------------------------------------------------


def test_is_coordinate_accepts_boundary() -> None:
    assert _is_coordinate(-90, -90, 90) is True
    assert _is_coordinate(90, -90, 90) is True
    assert _is_coordinate(-180, -180, 180) is True
    assert _is_coordinate(180, -180, 180) is True
    assert _is_coordinate(0, 0, 100) is True


def test_is_coordinate_rejects_non_numeric() -> None:
    assert _is_coordinate(True, 0, 100) is False  # bool is int subclass
    assert _is_coordinate("30", 0, 100) is False
    assert _is_coordinate(None, 0, 100) is False


# ---------------------------------------------------------------------------
# OpenSearchProjection — batch size validation
# ---------------------------------------------------------------------------


def test_opensearch_projection_rejects_zero_batch_size() -> None:
    embedder = BatchedEmbedder(FakeEmbeddingProvider(), dimension=3, batch_size=2)
    with pytest.raises(ValueError, match="greater than zero"):
        OpenSearchProjection(FakeOpenSearch(), "idx", embedder, bulk_batch_size=0)


def test_opensearch_projection_rejects_negative_batch_size() -> None:
    embedder = BatchedEmbedder(FakeEmbeddingProvider(), dimension=3, batch_size=2)
    with pytest.raises(ValueError, match="greater than zero"):
        OpenSearchProjection(FakeOpenSearch(), "idx", embedder, bulk_batch_size=-5)


# ---------------------------------------------------------------------------
# LocalSourceStorage additional edge cases (previously uncovered)
# ---------------------------------------------------------------------------


def test_local_source_storage_normalizes_windows_file_uri(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"windows-path")
    drive = source.drive
    if drive:
        # Simulate file:///C:/... which has leading / before drive letter
        posix_path = source.as_posix()
        uri = f"file:///{posix_path}"
        with LocalSourceStorage(tmp_path).open(uri) as stream:
            assert stream.read() == b"windows-path"


def test_local_source_storage_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LifecycleError) as captured:
        LocalSourceStorage(tmp_path).open("nonexistent.txt")
    assert captured.value.code == "SOURCE_NOT_FOUND"


def test_opensearch_projection_upsert_empty_chunks_skips_bulk(monkeypatch) -> None:
    client = FakeOpenSearch()
    bulk_called = False

    def fake_bulk(*_args, **_kwargs):
        nonlocal bulk_called
        bulk_called = True

    monkeypatch.setattr("app.etl.adapters.bulk", fake_bulk)
    embedder = BatchedEmbedder(FakeEmbeddingProvider(), dimension=3, batch_size=2)
    projection = OpenSearchProjection(client, "idx", embedder, bulk_batch_size=2)

    projection.upsert(VERSION_ID, [])

    assert not bulk_called
