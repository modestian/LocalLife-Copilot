from collections.abc import Iterable, Mapping
from typing import BinaryIO, Protocol, runtime_checkable
from uuid import UUID

from app.etl.models import ChunkRecord, DocumentRecord, JsonValue


@runtime_checkable
class Loader(Protocol):
    """Extract canonical records from a source without applying business cleaning."""

    def load(
        self,
        source: BinaryIO,
        *,
        source_key: str,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> Iterable[DocumentRecord]: ...


@runtime_checkable
class Cleaner(Protocol):
    """Apply configured cleaning steps in order and annotate their outcomes."""

    def clean(self, records: Iterable[DocumentRecord]) -> Iterable[DocumentRecord]: ...


@runtime_checkable
class Splitter(Protocol):
    """Split cleaned records into ordered chunks for one immutable document version."""

    def split(
        self,
        records: Iterable[DocumentRecord],
        *,
        document_version_id: UUID,
    ) -> Iterable[ChunkRecord]: ...
