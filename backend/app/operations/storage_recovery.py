"""MySQL/OpenSearch reconciliation and fail-closed index rebuilding."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID

from app.etl.lifecycle import projection_id
from app.etl.models import ChunkRecord, JsonValue


@dataclass(frozen=True, slots=True)
class ChunkFact:
    chunk_id: UUID
    tenant_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    document_version_id: UUID
    chunk_no: int
    content: str
    content_hash: str
    token_count: int
    page_number: int | None
    source_key: str
    source_type: str
    metadata: dict[str, JsonValue]
    stored_projection_id: str

    @property
    def projection_id(self) -> str:
        return projection_id(self.document_version_id, self.chunk_no)

    def to_chunk_record(self) -> ChunkRecord:
        # Scope fields come from relational joins, never from mutable metadata.
        trusted_metadata = dict(self.metadata)
        trusted_metadata.update(
            {
                "chunk_id": str(self.chunk_id),
                "tenant_id": str(self.tenant_id),
                "knowledge_base_id": str(self.knowledge_base_id),
                "document_id": str(self.document_id),
                "resource_scope": [f"KNOWLEDGE_BASE:{self.knowledge_base_id}"],
                "source_key": self.source_key,
                "source_type": self.source_type,
            }
        )
        return ChunkRecord(
            document_version_id=self.document_version_id,
            chunk_no=self.chunk_no,
            content=self.content,
            content_hash=self.content_hash,
            token_count=self.token_count,
            page_number=self.page_number,
            metadata=trusted_metadata,
        )


@dataclass(frozen=True, slots=True)
class ProjectionRecord:
    projection_id: str
    document_version_id: str | None
    chunk_no: int | None
    content_hash: str | None

    @property
    def logical_id(self) -> str | None:
        if self.document_version_id is None or self.chunk_no is None:
            return None
        return f"{self.document_version_id}:{self.chunk_no}"


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    mysql_count: int
    opensearch_count: int
    missing_projection_ids: tuple[str, ...]
    duplicate_logical_ids: dict[str, tuple[str, ...]]
    orphan_projection_ids: tuple[str, ...]
    drifted_projection_ids: tuple[str, ...]
    noncanonical_mysql_ids: dict[str, str]

    @property
    def projection_consistent(self) -> bool:
        return (
            not any(
                (
                    self.missing_projection_ids,
                    self.duplicate_logical_ids,
                    self.orphan_projection_ids,
                    self.drifted_projection_ids,
                )
            )
            and self.mysql_count == self.opensearch_count
        )

    @property
    def consistent(self) -> bool:
        return self.projection_consistent and not self.noncanonical_mysql_ids

    def to_json(self) -> dict[str, object]:
        return {"consistent": self.consistent, **asdict(self)}


class ChunkFactSource(Protocol):
    def list_indexable_chunks(self) -> Sequence[ChunkFact]: ...

    def mark_projection_ids_canonical(self, facts: Sequence[ChunkFact]) -> None: ...


class ProjectionStore(Protocol):
    def create_index(self, index: str) -> None: ...

    def list_projections(self, index: str) -> Sequence[ProjectionRecord]: ...

    def upsert(
        self, index: str, document_version_id: UUID, chunks: Sequence[ChunkRecord]
    ) -> None: ...

    def switch_aliases(self, index: str) -> None: ...


def reconcile(
    facts: Sequence[ChunkFact], projections: Sequence[ProjectionRecord]
) -> ReconciliationReport:
    expected = {fact.projection_id: fact for fact in facts}
    projected_ids = {record.projection_id for record in projections}
    logical_groups: dict[str, list[str]] = defaultdict(list)
    orphan_ids: list[str] = []
    drifted_ids: list[str] = []

    for record in projections:
        logical_id = record.logical_id
        if logical_id is None or logical_id not in expected:
            orphan_ids.append(record.projection_id)
            continue
        logical_groups[logical_id].append(record.projection_id)
        fact = expected[logical_id]
        if record.projection_id == logical_id and record.content_hash != fact.content_hash:
            drifted_ids.append(record.projection_id)

    duplicates = {
        logical_id: tuple(sorted(ids))
        for logical_id, ids in sorted(logical_groups.items())
        if len(ids) > 1
    }
    noncanonical = {
        fact.projection_id: fact.stored_projection_id
        for fact in facts
        if fact.stored_projection_id != fact.projection_id
    }
    return ReconciliationReport(
        mysql_count=len(facts),
        opensearch_count=len(projections),
        missing_projection_ids=tuple(sorted(set(expected) - projected_ids)),
        duplicate_logical_ids=duplicates,
        orphan_projection_ids=tuple(sorted(orphan_ids)),
        drifted_projection_ids=tuple(sorted(drifted_ids)),
        noncanonical_mysql_ids=dict(sorted(noncanonical.items())),
    )


class IndexRebuildService:
    """Build a fresh projection and switch aliases only after exact reconciliation."""

    def __init__(self, facts: ChunkFactSource, projections: ProjectionStore) -> None:
        self._facts = facts
        self._projections = projections

    def rebuild(self, target_index: str, *, allow_empty: bool = False) -> ReconciliationReport:
        chunks = list(self._facts.list_indexable_chunks())
        if not chunks and not allow_empty:
            raise RuntimeError("refusing to rebuild an empty MySQL fact set")
        self._projections.create_index(target_index)
        grouped: dict[UUID, list[ChunkRecord]] = defaultdict(list)
        for fact in chunks:
            grouped[fact.document_version_id].append(fact.to_chunk_record())
        for version_id, records in grouped.items():
            self._projections.upsert(target_index, version_id, records)

        projected = self._projections.list_projections(target_index)
        report = reconcile(chunks, projected)
        if not report.projection_consistent:
            raise RebuildConsistencyError(report)
        self._facts.mark_projection_ids_canonical(chunks)
        report = reconcile(self._facts.list_indexable_chunks(), projected)
        if not report.consistent:
            raise RebuildConsistencyError(report)
        self._projections.switch_aliases(target_index)
        return report


class RebuildConsistencyError(RuntimeError):
    def __init__(self, report: ReconciliationReport) -> None:
        super().__init__("rebuilt index differs from the MySQL fact source; aliases unchanged")
        self.report = report
