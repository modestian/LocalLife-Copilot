"""SQLAlchemy implementation of DatasetRepository.

Provides production-grade persistence for dataset metadata, implementing
the :class:`~app.application.dataset_service.DatasetRepository` Protocol.

All methods are async and use ``async_sessionmaker`` for connection management,
following the same pattern as :class:`SQLAlchemyAuthRepository`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.dataset_service import DatasetRecord
from app.core.ids import uuid7
from app.infrastructure.db.models.feedback import Dataset, DatasetItem


def _orm_to_record(ds: Dataset) -> DatasetRecord:
    """Convert a Dataset ORM row to a framework-agnostic DatasetRecord."""
    return DatasetRecord(
        id=ds.id,
        name=ds.name,
        task_type=ds.task_type,
        dataset_hash=ds.dataset_hash,
        storage_uri=ds.storage_uri,
        filter_config_json=ds.filter_config_json,
        redaction_version=ds.redaction_version,
        split_config_json=ds.split_config_json,
        sample_count=ds.sample_count,
        statistics_json=ds.statistics_json,
        status=ds.status,
        quality_report_uri=ds.quality_report_uri,
        quality_report_hash=ds.quality_report_hash,
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


class SQLAlchemyDatasetRepository:
    """Production DatasetRepository backed by async SQLAlchemy.

    Implements both methods of the DatasetRepository Protocol:
    ``save_dataset`` and ``get_dataset``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_dataset(self, record: DatasetRecord) -> DatasetRecord:
        """Insert a new dataset record and return the stored row."""
        async with self._session_factory() as session, session.begin():
            ds = Dataset(
                id=record.id,
                name=record.name,
                task_type=record.task_type,
                dataset_hash=record.dataset_hash,
                storage_uri=record.storage_uri,
                filter_config_json=record.filter_config_json,
                redaction_version=record.redaction_version,
                split_config_json=record.split_config_json,
                sample_count=record.sample_count,
                statistics_json=record.statistics_json,
                status=record.status,
                quality_report_uri=record.quality_report_uri,
                quality_report_hash=record.quality_report_hash,
            )
            session.add(ds)
            await session.flush()
            await session.refresh(ds)
            return _orm_to_record(ds)

    async def get_dataset(self, dataset_id: UUID) -> DatasetRecord | None:
        """Return a dataset by ID, or None if not found."""
        async with self._session_factory() as session:
            ds = await session.scalar(select(Dataset).where(Dataset.id == dataset_id))
            if ds is None:
                return None
            return _orm_to_record(ds)

    async def save_dataset_items(self, dataset_id: UUID, assignments: list[object]) -> None:
        """Persist the immutable train/validation/test assignment for each sample."""
        async with self._session_factory() as session, session.begin():
            for assignment in assignments:
                record = assignment.record
                session.add(
                    DatasetItem(
                        id=uuid7(),
                        dataset_id=dataset_id,
                        feedback_id=record.id,
                        message_id=record.message_id,
                        user_id=record.user_id,
                        split=assignment.split,
                        content_json=dict(assignment.content_json),
                        content_hash=assignment.content_hash,
                    )
                )
