import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias
from uuid import UUID

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
Metadata: TypeAlias = dict[str, JsonValue]

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class CleanStatus(StrEnum):
    """Outcome assigned to a document record by the cleaning pipeline."""

    CLEANED = "CLEANED"
    DROPPED = "DROPPED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


def _validate_content_hash(content_hash: str) -> None:
    if _SHA256_PATTERN.fullmatch(content_hash) is None:
        raise ValueError("content_hash must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Canonical row exchanged by loaders and cleaners.

    ``source_key`` is stable and unique within its source. Metadata is JSON-compatible
    and carries source-specific attributes such as location, page, or merchant_id.
    """

    content: str
    metadata: Metadata
    source_key: str
    content_hash: str
    clean_status: CleanStatus

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValueError("source_key must not be blank")
        _validate_content_hash(self.content_hash)


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """Canonical splitter output ready for persistence and embedding."""

    document_version_id: UUID
    chunk_no: int
    content: str
    content_hash: str
    token_count: int
    metadata: Metadata
    page_number: int | None = None

    def __post_init__(self) -> None:
        if self.chunk_no < 0:
            raise ValueError("chunk_no must be greater than or equal to zero")
        if not self.content.strip():
            raise ValueError("content must not be blank")
        _validate_content_hash(self.content_hash)
        if self.token_count <= 0:
            raise ValueError("token_count must be greater than zero")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be greater than or equal to one")
