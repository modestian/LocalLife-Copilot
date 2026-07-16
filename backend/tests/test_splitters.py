from dataclasses import replace
from uuid import UUID

import pytest

from app.etl import (
    CleanStatus,
    DocumentRecord,
    RecursiveSplitter,
    SemanticSplitter,
    Splitter,
    SplitterConfigError,
    stable_content_hash,
)

VERSION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b120")


def record(content: str, *, source_key: str = "reviews.md#1") -> DocumentRecord:
    return DocumentRecord(
        content=content,
        metadata={"page": 2, "merchant_id": "merchant-1"},
        source_key=source_key,
        content_hash=stable_content_hash(content),
        clean_status=CleanStatus.CLEANED,
    )


def test_recursive_splitter_preserves_order_overlap_metadata_and_quality() -> None:
    splitter = RecursiveSplitter(chunk_size=12, chunk_overlap=3)
    chunks = splitter.split(
        [record("第一段内容。第二段内容。第三段内容。")], document_version_id=VERSION_ID
    )
    assert isinstance(splitter, Splitter)
    assert len(chunks) >= 2
    assert [chunk.chunk_no for chunk in chunks] == list(range(len(chunks)))
    assert all(len(chunk.content) <= 12 for chunk in chunks)
    assert chunks[1].content.startswith(chunks[0].content[-3:])
    assert all(chunk.document_version_id == VERSION_ID for chunk in chunks)
    assert all(chunk.page_number == 2 for chunk in chunks)
    assert chunks[0].metadata["splitter"]["strategy"] == "recursive"
    assert chunks[0].metadata["splitter"]["chunk_size"] == 12
    assert splitter.last_report is not None
    assert splitter.last_report.chunk_count == len(chunks)
    assert splitter.last_report.max_chunk_characters <= 12
    assert splitter.last_report.total_tokens == sum(chunk.token_count for chunk in chunks)


def test_recursive_overlap_does_not_drop_source_content() -> None:
    source = "abcdefghijKLMNOPQRST"
    splitter = RecursiveSplitter(chunk_size=10, chunk_overlap=2)

    chunks = splitter.split([record(source)], document_version_id=VERSION_ID)

    reconstructed = chunks[0].content + "".join(chunk.content[2:] for chunk in chunks[1:])
    assert reconstructed == source
    assert all(len(chunk.content) <= 10 for chunk in chunks)


def test_normalized_chunk_hash_is_stable_across_unicode_and_newlines() -> None:
    composed = "café\r\n安静"
    decomposed = "cafe\u0301\n安静"
    first = RecursiveSplitter(chunk_size=100, chunk_overlap=0).split(
        [record(composed)], document_version_id=VERSION_ID
    )[0]
    second = RecursiveSplitter(chunk_size=100, chunk_overlap=0).split(
        [record(decomposed)], document_version_id=VERSION_ID
    )[0]
    assert first.content_hash == second.content_hash
    assert first.content_hash == stable_content_hash(composed)


def test_quality_report_counts_duplicates_and_skipped_records() -> None:
    splitter = RecursiveSplitter(chunk_size=100, chunk_overlap=0)
    dropped = replace(record("不应切分", source_key="dropped"), clean_status=CleanStatus.DROPPED)
    splitter.split(
        [record("相同内容", source_key="a"), record("相同内容", source_key="b"), dropped],
        document_version_id=VERSION_ID,
    )
    assert splitter.last_report is not None
    assert splitter.last_report.input_records == 3
    assert splitter.last_report.skipped_records == 1
    assert splitter.last_report.chunk_count == 2
    assert splitter.last_report.duplicate_chunks == 1


def test_semantic_splitter_breaks_at_low_similarity_and_saves_parameters() -> None:
    vectors = [[1.0, 0.0], [0.9, 0.1], [-1.0, 0.0]]
    splitter = SemanticSplitter(
        chunk_size=100,
        chunk_overlap=0,
        similarity_threshold=0.5,
        encoder=lambda sentences: vectors[: len(sentences)],
    )
    chunks = splitter.split(
        [record("环境安静。适合学习。火锅非常麻辣。")], document_version_id=VERSION_ID
    )
    assert [chunk.content for chunk in chunks] == ["环境安静。适合学习。", "火锅非常麻辣。"]
    assert chunks[0].metadata["splitter"] == {
        "strategy": "semantic",
        "chunk_size": 100,
        "chunk_overlap": 0,
        "similarity_threshold": 0.5,
        "encoder": "function",
    }
    assert splitter.last_report is not None
    assert splitter.last_report.strategy == "semantic"


def test_semantic_splitter_default_encoder_is_deterministic_and_runnable() -> None:
    source = record("环境安静。环境非常安静。火锅麻辣鲜香。")
    splitter = SemanticSplitter(chunk_size=20, chunk_overlap=2)
    first = splitter.split([source], document_version_id=VERSION_ID)
    second = splitter.split([source], document_version_id=VERSION_ID)
    assert [chunk.content_hash for chunk in first] == [chunk.content_hash for chunk in second]
    assert all(chunk.token_count > 0 for chunk in first)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"chunk_size": 0}, "chunk_size"),
        ({"chunk_size": 10, "chunk_overlap": 10}, "chunk_overlap"),
        ({"chunk_overlap": -1}, "chunk_overlap"),
    ],
)
def test_splitter_rejects_invalid_sizes(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(SplitterConfigError, match=message):
        RecursiveSplitter(**kwargs)


def test_semantic_splitter_rejects_invalid_encoder_output() -> None:
    splitter = SemanticSplitter(encoder=lambda sentences: [])
    with pytest.raises(SplitterConfigError, match="one vector per sentence"):
        splitter.split([record("第一句。第二句。")], document_version_id=VERSION_ID)
