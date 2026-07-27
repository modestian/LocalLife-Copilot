"""Production adapters for ingestion source files and search projections."""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

from app.etl.embeddings import BatchedEmbedder
from app.etl.lifecycle import LifecycleError, projection_id
from app.etl.models import ChunkRecord, JsonValue


class LocalSourceStorage:
    """Open only regular files contained by the configured knowledge-data root."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()

    def open(self, uri: str) -> AbstractContextManager[BinaryIO]:
        parsed = urlparse(uri)
        if parsed.scheme not in {"", "file"} or parsed.netloc not in {"", "localhost"}:
            raise LifecycleError("SOURCE_URI_UNSUPPORTED", "only local file sources are supported")
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else uri
        if (
            parsed.scheme == "file"
            and len(raw_path) >= 3
            and raw_path[0] == "/"
            and raw_path[2] == ":"
        ):
            raw_path = raw_path[1:]
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self._root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self._root):
            raise LifecycleError("SOURCE_PATH_FORBIDDEN", "source path escapes the data root")
        if not resolved.is_file():
            raise LifecycleError("SOURCE_NOT_FOUND", "source file does not exist")
        return resolved.open("rb")


class OpenSearchProjection:
    """Idempotent Chunk projection using document-version/chunk-number IDs."""

    def __init__(
        self,
        client: OpenSearch,
        index: str,
        embedder: BatchedEmbedder,
        *,
        bulk_batch_size: int = 500,
    ) -> None:
        if bulk_batch_size <= 0:
            raise ValueError("bulk batch size must be greater than zero")
        self._client = client
        self._index = index
        self._embedder = embedder
        self._bulk_batch_size = bulk_batch_size

    def upsert(self, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None:
        vectors = self._embedder.embed([chunk.content for chunk in chunks])
        actions = [
            {
                "_op_type": "index",
                "_index": self._index,
                "_id": projection_id(document_version_id, chunk.chunk_no),
                "_source": self._source(document_version_id, chunk, vector),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if actions:
            bulk(
                self._client,
                actions,
                chunk_size=self._bulk_batch_size,
                refresh="wait_for",
                raise_on_error=True,
                raise_on_exception=True,
            )

    def delete(self, document_version_id: UUID) -> int:
        response = self._client.delete_by_query(
            index=self._index,
            body={"query": {"term": {"document_version_id": str(document_version_id)}}},
            conflicts="proceed",
            refresh=True,
        )
        return int(response.get("deleted", 0))

    def count(self, document_version_id: UUID) -> int:
        response = self._client.count(
            index=self._index,
            body={"query": {"term": {"document_version_id": str(document_version_id)}}},
        )
        return int(response["count"])

    @staticmethod
    def _source(
        document_version_id: UUID, chunk: ChunkRecord, vector: Sequence[float]
    ) -> dict[str, JsonValue]:
        # Sanitize metadata for OpenSearch: remove "location" to avoid dynamic
        # mapping conflicts (string filename vs geo object from merchant reviews).
        # The validated geo point is projected to the top-level "location" field
        # and the filename is preserved in "source_key".
        safe_metadata = {k: v for k, v in chunk.metadata.items() if k != "location"}
        source: dict[str, JsonValue] = {
            "document_version_id": str(document_version_id),
            "chunk_no": chunk.chunk_no,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "page_number": chunk.page_number,
            "metadata": safe_metadata,
            "source_key": chunk.metadata.get("source_key"),
            "content_vector": list(vector),
        }
        for field in (
            "chunk_id",
            "tenant_id",
            "document_id",
            "knowledge_base_id",
            "merchant_id",
            "business_status",
            "valid_from",
            "valid_to",
            "resource_scope",
            "source_type",
            "source_location",
            "category_ids",
            "price_cent",
            "distance_meter",
        ):
            if (value := chunk.metadata.get(field)) is not None:
                source[field] = value
        if (location := _geo_location(chunk.metadata.get("location"))) is not None:
            source["location"] = location
        return source


def _geo_location(value: object) -> dict[str, float] | list[float] | str | None:
    """Return a value accepted by the OpenSearch ``geo_point`` mapping.

    Loaders use ``location`` as a human-readable source locator. Projecting a
    filename or content hash into the search index's geographic field causes
    all real file uploads to fail indexing, so only validated coordinates are
    exposed as the top-level geo point.
    """

    if isinstance(value, Mapping):
        latitude = value.get("lat")
        longitude = value.get("lon")
        if _is_coordinate(latitude, -90, 90) and _is_coordinate(longitude, -180, 180):
            return {"lat": float(latitude), "lon": float(longitude)}
        return None
    if isinstance(value, list) and len(value) == 2:
        longitude, latitude = value
        if _is_coordinate(latitude, -90, 90) and _is_coordinate(longitude, -180, 180):
            return [float(longitude), float(latitude)]
        return None
    if isinstance(value, str):
        try:
            latitude, longitude = (float(part.strip()) for part in value.split(",", maxsplit=1))
        except ValueError:
            return None
        if _is_coordinate(latitude, -90, 90) and _is_coordinate(longitude, -180, 180):
            return f"{latitude},{longitude}"
    return None


def _is_coordinate(value: object, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and minimum <= value <= maximum
    )
