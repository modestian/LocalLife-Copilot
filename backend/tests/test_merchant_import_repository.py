from __future__ import annotations

import hashlib
from contextlib import AbstractContextManager
from types import TracebackType
from uuid import UUID, uuid4

from app.etl.models import CleanStatus, DocumentRecord
from app.infrastructure.db.models.operations import Merchant, Review
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent
from app.infrastructure.db.repositories.merchant_import import SQLAlchemyMerchantReviewImporter

TENANT_ID = UUID("70200000-0000-4000-8000-000000000001")


class FakeTransaction(AbstractContextManager["FakeSession"]):
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __enter__(self) -> FakeSession:
        return self.session

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def get(self, model: type[object], record_id: object) -> None:
        return None

    def scalar(self, statement: object) -> None:
        return None

    def add(self, record: object) -> None:
        self.added.append(record)

    def flush(self) -> None:
        for record in self.added:
            if isinstance(record, AsyncTask) and record.id is None:
                record.id = uuid4()


def import_record() -> DocumentRecord:
    row = {
        "merchant_key": "new-cafe-001",
        "merchant_name": "青禾小馆",
        "category": "咖啡馆",
        "address": "锦江区测试路1号",
        "longitude": 104.08,
        "latitude": 30.65,
        "avg_price_cent": 4800,
        "merchant_rating": 4.6,
        "business_status": "OPEN",
        "review_key": "review-001",
        "review_content": "环境安静并且有插座",
        "review_rating": 5,
        "reviewed_at": "2026-07-20T12:30:00+08:00",
    }
    content = str(row)
    return DocumentRecord(
        content=content,
        metadata={"row_data": row},
        source_key="merchant.csv#row=2",
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        clean_status=CleanStatus.CLEANED,
    )


def test_repository_writes_domain_rows_and_enqueues_analysis() -> None:
    session = FakeSession()
    importer = SQLAlchemyMerchantReviewImporter(session)  # type: ignore[arg-type]

    result = importer.import_records(TENANT_ID, (import_record(),))

    assert result.merchant_count == 1
    assert result.review_count == 1
    assert len(result.analysis_task_ids) == 1
    assert result.records[0].metadata["merchant_name"] == "青禾小馆"

    merchant = next(record for record in session.added if isinstance(record, Merchant))
    review = next(record for record in session.added if isinstance(record, Review))
    task = next(record for record in session.added if isinstance(record, AsyncTask))
    event = next(record for record in session.added if isinstance(record, OutboxEvent))

    assert review.merchant_id == merchant.id
    assert review.status == "PUBLISHED"
    assert task.task_type == "MERCHANT_ANALYSIS"
    assert task.resource_id == merchant.id
    assert event.event_type == "merchant.analysis"
    assert event.aggregate_id == task.id
