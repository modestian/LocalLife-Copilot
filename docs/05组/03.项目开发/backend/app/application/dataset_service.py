"""Dataset generation and retrieval service.

Implements the application-layer orchestration for dataset generation
defined in:
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.2:
  POST /api/v1/fine-tuning/datasets — generate immutable JSONL dataset
  GET  /api/v1/fine-tuning/datasets/{id} — return metadata and reports
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §4.5/§11.8:
  datasets table fields and immutability constraints

ST-501 acceptance criteria:
- ⑤ JSONL dataset immutable after generation; SHA-256, sample count,
  provenance and quality report stored.
- ⑥ Stratified split by entity or conversation, no leakage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.application.dataset_builder import DatasetBuilder, DatasetBuildResult
from app.application.feedback import FeedbackRepository
from app.domain.feedback import DatasetFilter, SplitConfig

# ---------------------------------------------------------------------------
# Dataset record (mirrors datasets table, framework-agnostic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    """In-memory representation of a dataset entry.

    Mirrors the columns of the ``datasets`` table without importing the
    SQLAlchemy model, so the application layer stays framework-agnostic.

    Per §4.5: once status == 'READY', all content fields are immutable.
    """

    id: UUID
    name: str
    task_type: str
    dataset_hash: str
    storage_uri: str
    filter_config_json: dict[str, object]
    redaction_version: str
    split_config_json: dict[str, object]
    sample_count: int
    statistics_json: dict[str, object]
    status: str
    quality_report_uri: str | None = None
    quality_report_hash: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class DatasetError(ValueError):
    """Base error for dataset domain violations."""


class DatasetNotFoundError(DatasetError):
    """The requested dataset does not exist."""


class EmptyDatasetError(DatasetError):
    """No feedback records matched the filter, so no dataset was generated."""


# ---------------------------------------------------------------------------
# Repository contract (Protocol)
# ---------------------------------------------------------------------------


class DatasetRepository(Protocol):
    """Port that the infrastructure dataset repository must satisfy."""

    async def save_dataset(self, record: DatasetRecord) -> DatasetRecord:
        """Insert a new dataset record.  Returns the stored record."""
        ...

    async def save_dataset_items(self, dataset_id: UUID, assignments: list[object]) -> None:
        """Persist immutable split assignments used by the training worker."""
        ...

    async def get_dataset(self, dataset_id: UUID) -> DatasetRecord | None:
        """Return a dataset by ID, or None if not found."""
        ...


# ---------------------------------------------------------------------------
# In-memory dataset repository (for tests)
# ---------------------------------------------------------------------------


class InMemoryDatasetRepository:
    """Simple in-memory implementation of :class:`DatasetRepository`."""

    def __init__(self) -> None:
        self._store: dict[UUID, DatasetRecord] = {}

    async def save_dataset(self, record: DatasetRecord) -> DatasetRecord:
        self._store[record.id] = record
        return record

    async def save_dataset_items(self, dataset_id: UUID, assignments: list[object]) -> None:
        # The in-memory repository is used by service tests; metadata is sufficient there.
        return None

    async def get_dataset(self, dataset_id: UUID) -> DatasetRecord | None:
        return self._store.get(dataset_id)


# ---------------------------------------------------------------------------
# Dataset service
# ---------------------------------------------------------------------------


class DatasetService:
    """Orchestrates dataset generation and retrieval.

    Pipeline (per §8.2 and acceptance criteria ⑤⑥):
    1. Query feedback records matching the filter (via FeedbackRepository).
    2. Run the DatasetBuilder pipeline (redact → quality → split → JSONL → hash).
    3. Persist the dataset metadata (via DatasetRepository).

    Usage:
        service = DatasetService(feedback_repo, dataset_repo)
        record = await service.generate_dataset(
            name="sentiment_v1",
            task_type="sentiment_classification",
            filter=DatasetFilter(...),
            split_config=SplitConfig(...),
        )
    """

    def __init__(
        self,
        feedback_repository: FeedbackRepository,
        dataset_repository: DatasetRepository,
        builder: DatasetBuilder | None = None,
    ) -> None:
        self._feedback_repo = feedback_repository
        self._dataset_repo = dataset_repository
        self._builder = builder or DatasetBuilder()

    async def generate_dataset(
        self,
        *,
        name: str,
        task_type: str,
        filter_config: DatasetFilter,
        split_config: SplitConfig | None = None,
        output_path: str | None = None,
    ) -> DatasetRecord:
        """Generate an immutable JSONL dataset from filtered feedback.

        Args:
            name: Dataset name (datasets.name).
            task_type: Training task type (datasets.task_type).
            filter_config: Filter conditions for feedback selection.
            split_config: Split configuration or None for defaults.
            output_path: Path for JSONL file, or None to skip file writing.

        Returns:
            The persisted :class:`DatasetRecord`.

        Raises:
            EmptyDatasetError: If no feedback matches the filter.
        """
        # Step 1: Query feedback records
        records = await self._feedback_repo.query_feedbacks(filter_config)
        if not records:
            raise EmptyDatasetError(
                "No feedback records matched the filter; cannot generate dataset"
            )

        # Step 2: Build dataset (redact → quality → split → JSONL → hash)
        result: DatasetBuildResult = self._builder.build(
            records=records,
            name=name,
            task_type=task_type,
            split_config=split_config,
            output_path=output_path,
        )

        # Step 3: Persist dataset metadata
        from app.core.ids import uuid7

        now = datetime.now(tz=UTC)
        record = DatasetRecord(
            id=uuid7(),
            name=name,
            task_type=task_type,
            dataset_hash=result.dataset_hash,
            storage_uri=result.storage_uri or "",
            filter_config_json=filter_config.model_dump(mode="json"),
            redaction_version=result.redaction_version,
            split_config_json=result.split_config,
            sample_count=result.sample_count,
            statistics_json=result.statistics,
            status="READY",
            quality_report_uri=None,
            quality_report_hash=None,
            created_at=now,
            updated_at=now,
        )
        saved = await self._dataset_repo.save_dataset(record)
        await self._dataset_repo.save_dataset_items(saved.id, list(result.assignments))
        return saved

    async def get_dataset(self, dataset_id: UUID) -> DatasetRecord:
        """Retrieve a dataset by ID.

        Raises:
            DatasetNotFoundError: If the dataset does not exist.
        """
        record = await self._dataset_repo.get_dataset(dataset_id)
        if record is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} not found")
        return record
