from dataclasses import replace
from uuid import UUID

import pytest

from app.operations.storage_recovery import (
    ChunkFact,
    IndexRebuildService,
    ProjectionRecord,
    RebuildConsistencyError,
    reconcile,
)

VERSION_ID = UUID("70200000-0000-4000-8000-000000000042")


def fact(chunk_no: int = 0) -> ChunkFact:
    return ChunkFact(
        chunk_id=UUID("70200000-0000-4000-8000-000000000044"),
        tenant_id=UUID("70200000-0000-4000-8000-000000000001"),
        knowledge_base_id=UUID("70200000-0000-4000-8000-000000000010"),
        document_id=UUID("70200000-0000-4000-8000-000000000040"),
        document_version_id=VERSION_ID,
        chunk_no=chunk_no,
        content="安静且有插座",
        content_hash="a" * 64,
        token_count=6,
        page_number=None,
        source_key="demo-cafe",
        source_type="MD",
        metadata={"tenant_id": "untrusted", "merchant_id": "merchant-1"},
        stored_projection_id=f"{VERSION_ID}:{chunk_no}",
    )


def projection(projection_id: str | None = None, *, content_hash: str = "a" * 64):
    return ProjectionRecord(
        projection_id=projection_id or f"{VERSION_ID}:0",
        document_version_id=str(VERSION_ID),
        chunk_no=0,
        content_hash=content_hash,
    )


def test_reconcile_accepts_an_exact_projection() -> None:
    report = reconcile([fact()], [projection()])

    assert report.consistent
    assert report.mysql_count == report.opensearch_count == 1


def test_reconcile_identifies_missing_duplicate_orphan_drift_and_noncanonical_ids() -> None:
    expected = replace(fact(), stored_projection_id="legacy-id")
    records = [
        projection(content_hash="changed"),
        projection("duplicate-id"),
        ProjectionRecord("orphan-id", None, None, None),
    ]

    report = reconcile([expected, fact(1)], records)

    assert report.missing_projection_ids == (f"{VERSION_ID}:1",)
    assert report.duplicate_logical_ids == {f"{VERSION_ID}:0": (f"{VERSION_ID}:0", "duplicate-id")}
    assert report.orphan_projection_ids == ("orphan-id",)
    assert report.drifted_projection_ids == (f"{VERSION_ID}:0",)
    assert report.noncanonical_mysql_ids == {f"{VERSION_ID}:0": "legacy-id"}
    assert not report.consistent


def test_chunk_record_overrides_untrusted_scope_metadata() -> None:
    record = fact().to_chunk_record()

    assert record.metadata["tenant_id"] == "70200000-0000-4000-8000-000000000001"
    assert record.metadata["knowledge_base_id"] == "70200000-0000-4000-8000-000000000010"
    assert record.metadata["merchant_id"] == "merchant-1"


class FactSource:
    def __init__(self, facts):
        self.facts = facts

    def list_indexable_chunks(self):
        return self.facts

    def mark_projection_ids_canonical(self, facts):
        self.facts = [replace(item, stored_projection_id=item.projection_id) for item in facts]


class ProjectionStore:
    def __init__(self, records):
        self.records = records
        self.actions = []

    def create_index(self, index):
        self.actions.append(("create", index))

    def upsert(self, index, document_version_id, chunks):
        self.actions.append(("upsert", index, document_version_id, len(chunks)))

    def list_projections(self, index):
        self.actions.append(("scan", index))
        return self.records

    def switch_aliases(self, index):
        self.actions.append(("switch", index))


def test_rebuild_switches_aliases_only_after_exact_reconciliation() -> None:
    store = ProjectionStore([projection()])

    report = IndexRebuildService(FactSource([fact()]), store).rebuild("chunks-v2")

    assert report.consistent
    assert store.actions[-1] == ("switch", "chunks-v2")


def test_rebuild_keeps_aliases_unchanged_when_verification_fails() -> None:
    store = ProjectionStore([])

    with pytest.raises(RebuildConsistencyError):
        IndexRebuildService(FactSource([fact()]), store).rebuild("chunks-v2")

    assert not any(action[0] == "switch" for action in store.actions)


def test_rebuild_refuses_an_empty_fact_source_by_default() -> None:
    store = ProjectionStore([])

    with pytest.raises(RuntimeError, match="empty MySQL fact set"):
        IndexRebuildService(FactSource([]), store).rebuild("chunks-v2")

    assert store.actions == []
