from collections.abc import Iterable, Mapping
from io import BytesIO
from typing import BinaryIO
from uuid import UUID, uuid4

import pytest

from app.etl import ChunkRecord, Cleaner, CleanStatus, DocumentRecord, Loader, Splitter
from app.etl.models import JsonValue

CONTENT_HASH = "a" * 64


def document_record(**overrides: object) -> DocumentRecord:
    values = {
        "content": "环境安静，适合聊天。",
        "metadata": {"source_type": "TXT", "page": 1},
        "source_key": "reviews/example.txt#1",
        "content_hash": CONTENT_HASH,
        "clean_status": CleanStatus.CLEANED,
    }
    values.update(overrides)
    return DocumentRecord(**values)  # type: ignore[arg-type]


def test_document_record_exposes_documented_canonical_fields() -> None:
    record = document_record()

    assert record.content == "环境安静，适合聊天。"
    assert record.metadata == {"source_type": "TXT", "page": 1}
    assert record.source_key == "reviews/example.txt#1"
    assert record.content_hash == CONTENT_HASH
    assert record.clean_status is CleanStatus.CLEANED


@pytest.mark.parametrize("content_hash", ["", "A" * 64, "a" * 63, "z" * 64])
def test_document_record_rejects_invalid_sha256(content_hash: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        document_record(content_hash=content_hash)


def test_document_record_rejects_blank_source_key() -> None:
    with pytest.raises(ValueError, match="source_key"):
        document_record(source_key="  ")


def test_chunk_record_enforces_persistence_constraints() -> None:
    version_id = uuid4()
    chunk = ChunkRecord(
        document_version_id=version_id,
        chunk_no=0,
        content="环境安静。",
        content_hash=CONTENT_HASH,
        token_count=4,
        metadata={"location": "第 1 页"},
        page_number=1,
    )

    assert chunk.document_version_id == version_id
    assert chunk.chunk_no == 0
    assert chunk.page_number == 1


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chunk_no": -1}, "chunk_no"),
        ({"content": "  "}, "content"),
        ({"content_hash": "invalid"}, "SHA-256"),
        ({"token_count": 0}, "token_count"),
        ({"page_number": 0}, "page_number"),
    ],
)
def test_chunk_record_rejects_invalid_values(overrides: dict[str, object], message: str) -> None:
    values = {
        "document_version_id": uuid4(),
        "chunk_no": 0,
        "content": "有效内容",
        "content_hash": CONTENT_HASH,
        "token_count": 2,
        "metadata": {},
        "page_number": None,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        ChunkRecord(**values)  # type: ignore[arg-type]


class StubLoader:
    def load(
        self,
        source: BinaryIO,
        *,
        source_key: str,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Iterable[DocumentRecord]:
        yield document_record(
            content=source.read().decode(),
            source_key=source_key,
            metadata=dict(metadata or {}),
        )


class StubCleaner:
    def clean(self, records: Iterable[DocumentRecord]) -> Iterable[DocumentRecord]:
        return records


class StubSplitter:
    def split(
        self,
        records: Iterable[DocumentRecord],
        *,
        document_version_id: UUID,
    ) -> Iterable[ChunkRecord]:
        for chunk_no, record in enumerate(records):
            yield ChunkRecord(
                document_version_id=document_version_id,
                chunk_no=chunk_no,
                content=record.content,
                content_hash=record.content_hash,
                token_count=1,
                metadata=record.metadata,
            )


def test_ports_support_structural_adapter_implementations() -> None:
    loader = StubLoader()
    cleaner = StubCleaner()
    splitter = StubSplitter()

    assert isinstance(loader, Loader)
    assert isinstance(cleaner, Cleaner)
    assert isinstance(splitter, Splitter)

    records = loader.load(BytesIO("示例".encode()), source_key="example.txt")
    chunks = list(splitter.split(cleaner.clean(records), document_version_id=uuid4()))
    assert [chunk.content for chunk in chunks] == ["示例"]
