"""Production adapters for storage reconciliation and index rebuilding."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from opensearchpy import OpenSearch
from opensearchpy.helpers import scan
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.etl.adapters import OpenSearchProjection
from app.etl.embeddings import BatchedEmbedder
from app.etl.models import ChunkRecord
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase
from app.infrastructure.search.indexes import create_chunk_index, switch_chunk_aliases
from app.operations.storage_recovery import ChunkFact, ProjectionRecord


class SQLAlchemyChunkFactSource:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list_indexable_chunks(self) -> Sequence[ChunkFact]:
        with self._session_factory() as session:
            rows = session.execute(
                select(Chunk, DocumentVersion, Document, KnowledgeBase)
                .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
                .where(
                    KnowledgeBase.status == "ACTIVE",
                    KnowledgeBase.deleted_at.is_(None),
                    Document.status == "READY",
                    Document.deleted_at.is_(None),
                    DocumentVersion.is_current.is_(True),
                    Document.current_version_no == DocumentVersion.version_no,
                    Chunk.index_status != "DELETED",
                )
                .order_by(DocumentVersion.id, Chunk.chunk_no)
            ).all()
            return [
                ChunkFact(
                    chunk_id=chunk.id,
                    tenant_id=knowledge_base.tenant_id,
                    knowledge_base_id=knowledge_base.id,
                    document_id=document.id,
                    document_version_id=version.id,
                    chunk_no=chunk.chunk_no,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_count,
                    page_number=chunk.page_number,
                    source_key=document.source_key,
                    source_type=document.source_type,
                    metadata=dict(chunk.metadata_json),
                    stored_projection_id=chunk.opensearch_document_id,
                )
                for chunk, version, document, knowledge_base in rows
            ]

    def mark_projection_ids_canonical(self, facts: Sequence[ChunkFact]) -> None:
        expected = {fact.chunk_id: fact.projection_id for fact in facts}
        if not expected:
            return
        with self._session_factory.begin() as session:
            chunks = session.scalars(
                select(Chunk).where(Chunk.id.in_(expected)).with_for_update()
            ).all()
            if len(chunks) != len(expected):
                raise RuntimeError("MySQL chunks changed during index rebuild")
            for chunk in chunks:
                chunk.opensearch_document_id = expected[chunk.id]
                chunk.index_status = "INDEXED"


class OpenSearchRebuildStore:
    def __init__(
        self,
        client: OpenSearch,
        embedder: BatchedEmbedder,
        *,
        read_alias: str,
        write_alias: str,
        embedding_dimension: int,
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._read_alias = read_alias
        self._write_alias = write_alias
        self._embedding_dimension = embedding_dimension

    def create_index(self, index: str) -> None:
        if self._client.indices.exists(index=index):
            raise RuntimeError(f"target index already exists: {index}")
        create_chunk_index(
            self._client,
            index=index,
            embedding_dimension=self._embedding_dimension,
        )

    def list_projections(self, index: str) -> Sequence[ProjectionRecord]:
        if not self._client.indices.exists(index=index):
            raise RuntimeError(f"index does not exist: {index}")
        hits = scan(
            self._client,
            index=index,
            query={"query": {"match_all": {}}},
            _source=["document_version_id", "chunk_no", "content_hash"],
            preserve_order=False,
        )
        records = []
        for hit in hits:
            source = hit.get("_source", {})
            records.append(
                ProjectionRecord(
                    projection_id=str(hit.get("_id", "")),
                    document_version_id=_optional_string(source.get("document_version_id")),
                    chunk_no=_optional_integer(source.get("chunk_no")),
                    content_hash=_optional_string(source.get("content_hash")),
                )
            )
        return records

    def upsert(self, index: str, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None:
        OpenSearchProjection(self._client, index, self._embedder).upsert(
            document_version_id, chunks
        )

    def switch_aliases(self, index: str) -> None:
        switch_chunk_aliases(
            self._client,
            index=index,
            read_alias=self._read_alias,
            write_alias=self._write_alias,
        )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
