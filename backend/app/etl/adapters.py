"""Production adapters for ingestion source files and search projections."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlparse
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

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

    def __init__(self, client: OpenSearch, index: str) -> None:
        self._client = client
        self._index = index

    def upsert(self, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None:
        actions = [
            {
                "_op_type": "index",
                "_index": self._index,
                "_id": projection_id(document_version_id, chunk.chunk_no),
                "_source": self._source(document_version_id, chunk),
            }
            for chunk in chunks
        ]
        if actions:
            bulk(self._client, actions, refresh="wait_for", raise_on_error=True)

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
    def _source(document_version_id: UUID, chunk: ChunkRecord) -> dict[str, JsonValue]:
        source: dict[str, JsonValue] = {
            "document_version_id": str(document_version_id),
            "chunk_no": chunk.chunk_no,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "page_number": chunk.page_number,
            "metadata": chunk.metadata,
            "source_key": chunk.metadata.get("source_key"),
        }
        for field in (
            "document_id",
            "knowledge_base_id",
            "merchant_id",
            "business_status",
            "valid_from",
            "valid_to",
            "resource_scope",
        ):
            if (value := chunk.metadata.get(field)) is not None:
                source[field] = value
        return source
