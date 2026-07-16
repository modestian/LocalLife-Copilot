"""Deterministic recursive and semantic text splitters."""

import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TypeAlias
from uuid import UUID

from app.etl.loaders import normalized_content_hash
from app.etl.models import ChunkRecord, CleanStatus, DocumentRecord, Metadata

EmbeddingVector: TypeAlias = Sequence[float]
EmbeddingFunction: TypeAlias = Callable[[Sequence[str]], Sequence[EmbeddingVector]]

DEFAULT_SEPARATORS = (
    "\n\n",
    "\n",
    "。",
    "！",
    "？",
    ". ",
    "! ",
    "? ",
    "；",
    "; ",
    "，",
    ", ",
    " ",
    "",
)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\.])\s*|\n+")
_TOKEN = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9_]+|[^\s]")


class SplitterConfigError(ValueError):
    """Raised when splitter parameters cannot produce valid chunks."""


@dataclass(frozen=True, slots=True)
class SplitQualityReport:
    strategy: str
    input_records: int
    skipped_records: int
    chunk_count: int
    duplicate_chunks: int
    total_characters: int
    total_tokens: int
    min_chunk_characters: int
    max_chunk_characters: int
    average_chunk_characters: float
    duration_ms: float
    parameters: Metadata


def stable_content_hash(content: str) -> str:
    """Return the canonical SHA-256 used for idempotent chunk comparison."""
    return normalized_content_hash(content)


def count_tokens(content: str) -> int:
    """Return a deterministic dependency-free token estimate for storage statistics."""
    return len(_TOKEN.findall(unicodedata.normalize("NFC", content)))


def _validate_size(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_size <= 0:
        raise SplitterConfigError("chunk_size must be greater than zero")
    if chunk_overlap < 0:
        raise SplitterConfigError("chunk_overlap must be greater than or equal to zero")
    if chunk_overlap >= chunk_size:
        raise SplitterConfigError("chunk_overlap must be less than chunk_size")


def _hard_split(text: str, chunk_size: int) -> list[str]:
    return [text[start : start + chunk_size] for start in range(0, len(text), chunk_size)]


def _split_recursive(text: str, chunk_size: int, separators: Sequence[str]) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    separator = next((item for item in separators if item and item in text), "")
    if not separator:
        return _hard_split(text, chunk_size)
    remaining = separators[separators.index(separator) + 1 :]
    pieces = text.split(separator)
    units = [
        piece + separator if index < len(pieces) - 1 else piece
        for index, piece in enumerate(pieces)
    ]
    result: list[str] = []
    buffer = ""
    for unit in units:
        if not unit:
            continue
        if len(buffer) + len(unit) <= chunk_size:
            buffer += unit
            continue
        if buffer:
            result.append(buffer)
            buffer = ""
        if len(unit) <= chunk_size:
            buffer = unit
        else:
            result.extend(_split_recursive(unit, chunk_size, remaining))
    if buffer:
        result.append(buffer)
    return result


def _with_overlap(chunks: Sequence[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_overlap == 0 or len(chunks) < 2:
        return list(chunks)
    result = [chunks[0]]
    for index in range(1, len(chunks)):
        prefix = chunks[index - 1][-chunk_overlap:]
        result.append((prefix + chunks[index])[:chunk_size])
    return result


def _page_number(metadata: Metadata) -> int | None:
    page = metadata.get("page")
    return page if isinstance(page, int) and not isinstance(page, bool) and page >= 1 else None


class _BaseSplitter:
    strategy: str

    def __init__(self, *, chunk_size: int = 500, chunk_overlap: int = 80) -> None:
        _validate_size(chunk_size, chunk_overlap)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.last_report: SplitQualityReport | None = None

    def _parameters(self) -> Metadata:
        return {"chunk_size": self.chunk_size, "chunk_overlap": self.chunk_overlap}

    def _split_content(self, content: str) -> list[str]:
        raise NotImplementedError

    def split(
        self, records: Iterable[DocumentRecord], *, document_version_id: UUID
    ) -> list[ChunkRecord]:
        started = time.perf_counter()
        source_records = list(records)
        chunks: list[ChunkRecord] = []
        skipped = 0
        parameters = self._parameters()
        for record in source_records:
            if record.clean_status is not CleanStatus.CLEANED or not record.content.strip():
                skipped += 1
                continue
            for content in self._split_content(record.content):
                if not content.strip():
                    continue
                metadata: Metadata = dict(record.metadata)
                metadata["source_key"] = record.source_key
                metadata["splitter"] = {"strategy": self.strategy, **parameters}
                chunks.append(
                    ChunkRecord(
                        document_version_id=document_version_id,
                        chunk_no=len(chunks),
                        content=content,
                        content_hash=stable_content_hash(content),
                        token_count=count_tokens(content),
                        metadata=metadata,
                        page_number=_page_number(record.metadata),
                    )
                )
        sizes = [len(chunk.content) for chunk in chunks]
        hashes = [chunk.content_hash for chunk in chunks]
        self.last_report = SplitQualityReport(
            strategy=self.strategy,
            input_records=len(source_records),
            skipped_records=skipped,
            chunk_count=len(chunks),
            duplicate_chunks=len(hashes) - len(set(hashes)),
            total_characters=sum(sizes),
            total_tokens=sum(chunk.token_count for chunk in chunks),
            min_chunk_characters=min(sizes, default=0),
            max_chunk_characters=max(sizes, default=0),
            average_chunk_characters=sum(sizes) / len(sizes) if sizes else 0.0,
            duration_ms=(time.perf_counter() - started) * 1000,
            parameters=parameters,
        )
        return chunks


class RecursiveSplitter(_BaseSplitter):
    """Split text on progressively finer structural boundaries."""

    strategy = "recursive"

    def __init__(
        self,
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
        separators: Sequence[str] = DEFAULT_SEPARATORS,
    ) -> None:
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not separators or separators[-1] != "":
            raise SplitterConfigError("separators must end with an empty hard-split fallback")
        self.separators = tuple(separators)

    def _parameters(self) -> Metadata:
        return {**super()._parameters(), "separators": list(self.separators)}

    def _split_content(self, content: str) -> list[str]:
        content_size = self.chunk_size - self.chunk_overlap
        chunks = _split_recursive(content, content_size, self.separators)
        return _with_overlap(chunks, self.chunk_size, self.chunk_overlap)


class HashingSentenceEncoder:
    """Small deterministic encoder suitable as an offline semantic-split fallback."""

    def __init__(self, dimensions: int = 128) -> None:
        if dimensions <= 0:
            raise SplitterConfigError("encoder dimensions must be greater than zero")
        self.dimensions = dimensions

    def __call__(self, sentences: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for sentence in sentences:
            vector = [0.0] * self.dimensions
            normalized = unicodedata.normalize("NFC", sentence).casefold()
            features = _TOKEN.findall(normalized)
            features.extend(normalized[index : index + 2] for index in range(len(normalized) - 1))
            for feature in features:
                digest = hashlib.sha256(feature.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[index] += 1.0 if digest[4] & 1 else -1.0
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector] if norm else vector)
        return vectors


def _cosine_similarity(left: EmbeddingVector, right: EmbeddingVector) -> float:
    if len(left) != len(right) or not left:
        raise SplitterConfigError("embedding vectors must be non-empty and have equal dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class SemanticSplitter(_BaseSplitter):
    """Group adjacent sentences while their embedding similarity remains coherent."""

    strategy = "semantic"

    def __init__(
        self,
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 80,
        similarity_threshold: float = 0.35,
        encoder: EmbeddingFunction | None = None,
    ) -> None:
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not -1.0 <= similarity_threshold <= 1.0:
            raise SplitterConfigError("similarity_threshold must be between -1 and 1")
        self.similarity_threshold = similarity_threshold
        self.encoder = encoder or HashingSentenceEncoder()

    def _parameters(self) -> Metadata:
        return {
            **super()._parameters(),
            "similarity_threshold": self.similarity_threshold,
            "encoder": type(self.encoder).__name__,
        }

    def _split_content(self, content: str) -> list[str]:
        sentences = [item for item in _SENTENCE_BOUNDARY.split(content) if item.strip()]
        if not sentences:
            return []
        vectors = list(self.encoder(sentences))
        if len(vectors) != len(sentences):
            raise SplitterConfigError("encoder must return one vector per sentence")
        content_size = self.chunk_size - self.chunk_overlap
        groups: list[str] = []
        current = sentences[0]
        for index in range(1, len(sentences)):
            sentence = sentences[index]
            coherent = (
                _cosine_similarity(vectors[index - 1], vectors[index]) >= self.similarity_threshold
            )
            if coherent and len(current) + len(sentence) <= content_size:
                current += sentence
            else:
                groups.append(current)
                current = sentence
        groups.append(current)
        sized: list[str] = []
        for group in groups:
            sized.extend(_split_recursive(group, content_size, DEFAULT_SEPARATORS))
        return _with_overlap(sized, self.chunk_size, self.chunk_overlap)
