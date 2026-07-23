"""SQLAlchemy projection for validated merchant-review import rows."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.etl.merchant_reviews import (
    MerchantReviewImportError,
    MerchantReviewImportResult,
    MerchantReviewRow,
    enrich_source_record,
    parse_merchant_review_rows,
)
from app.etl.models import DocumentRecord
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.identity import ResourceGrant, User
from app.infrastructure.db.models.operations import Merchant, Review
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent


class SQLAlchemyMerchantReviewImporter:
    """Upsert merchant domain rows and return records enriched for retrieval."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def import_records(
        self, tenant_id: UUID, records: tuple[DocumentRecord, ...]
    ) -> MerchantReviewImportResult:
        rows = parse_merchant_review_rows(tenant_id, records)
        analysis_task_ids: list[UUID] = []
        with self._session_factory.begin() as session:
            owners = self._resolve_owners(session, tenant_id, rows)
            for row in rows:
                self._upsert_merchant(session, tenant_id, row)
                self._upsert_review(session, tenant_id, row)
                if row.owner_username is not None:
                    self._grant_read(session, owners[row.owner_username], row.merchant_id)
            session.flush()
            for merchant_id in sorted({row.merchant_id for row in rows}):
                analysis_task_ids.append(self._enqueue_analysis(session, merchant_id))
        return MerchantReviewImportResult(
            records=tuple(enrich_source_record(row) for row in rows),
            merchant_count=len({row.merchant_id for row in rows}),
            review_count=len(rows),
            analysis_task_ids=tuple(analysis_task_ids),
        )

    @staticmethod
    def _resolve_owners(
        session: Session, tenant_id: UUID, rows: Sequence[MerchantReviewRow]
    ) -> dict[str, UUID]:
        usernames = {row.owner_username for row in rows if row.owner_username is not None}
        if not usernames:
            return {}
        users = session.scalars(
            select(User).where(
                User.normalized_username.in_({value.casefold() for value in usernames}),
                User.status == "ACTIVE",
                User.deleted_at.is_(None),
                User.department_id == tenant_id,
            )
        ).all()
        resolved = {user.normalized_username: user.id for user in users}
        missing = sorted(value for value in usernames if value.casefold() not in resolved)
        if missing:
            raise MerchantReviewImportError(
                f"owner_username 不存在、不属于当前租户或不可用：{', '.join(missing)}"
            )
        return {value: resolved[value.casefold()] for value in usernames}

    @staticmethod
    def _upsert_merchant(session: Session, tenant_id: UUID, row: MerchantReviewRow) -> None:
        merchant = session.get(Merchant, row.merchant_id)
        if merchant is None:
            merchant = Merchant(id=row.merchant_id)
            session.add(merchant)
        merchant.region_id = tenant_id
        merchant.category = row.category
        merchant.name = row.merchant_name
        merchant.normalized_name = " ".join(row.merchant_name.casefold().split())
        merchant.address = row.address
        merchant.longitude = row.longitude
        merchant.latitude = row.latitude
        merchant.avg_price_cent = row.avg_price_cent
        merchant.rating = row.merchant_rating
        merchant.business_status = row.business_status
        merchant.last_verified_at = utc_now()

    @staticmethod
    def _upsert_review(session: Session, tenant_id: UUID, row: MerchantReviewRow) -> None:
        source_review_id = _source_review_id(tenant_id, row.merchant_key, row.review_key)
        review = session.scalar(
            select(Review).where(
                Review.source_type == "FILE_IMPORT",
                Review.source_review_id == source_review_id,
            )
        )
        if review is None:
            review = Review(
                merchant_id=row.merchant_id,
                source_type="FILE_IMPORT",
                source_review_id=source_review_id,
            )
            session.add(review)
        review.merchant_id = row.merchant_id
        review.author_ref = row.author_ref
        review.content = row.review_content
        review.content_hash = hashlib.sha256(row.review_content.encode("utf-8")).hexdigest()
        review.rating = row.review_rating
        review.reviewed_at = row.reviewed_at
        review.status = "PUBLISHED"
        review.tags_json = list(row.tags)

    @staticmethod
    def _grant_read(session: Session, user_id: UUID, merchant_id: UUID) -> None:
        grant = session.scalar(
            select(ResourceGrant.id).where(
                ResourceGrant.subject_type == "USER",
                ResourceGrant.subject_id == user_id,
                ResourceGrant.resource_type == "MERCHANT",
                ResourceGrant.resource_id == merchant_id,
                ResourceGrant.action == "READ",
            )
        )
        if grant is None:
            session.add(
                ResourceGrant(
                    subject_type="USER",
                    subject_id=user_id,
                    resource_type="MERCHANT",
                    resource_id=merchant_id,
                    action="READ",
                )
            )

    @staticmethod
    def _enqueue_analysis(session: Session, merchant_id: UUID) -> UUID:
        task = AsyncTask(
            task_type="MERCHANT_ANALYSIS",
            resource_type="MERCHANT",
            resource_id=merchant_id,
            result_json={"mode": "FULL", "since": None},
        )
        session.add(task)
        session.flush()
        session.add(
            OutboxEvent(
                aggregate_type="ASYNC_TASK",
                aggregate_id=task.id,
                event_type="merchant.analysis",
                event_version=1,
                payload_json={
                    "task_id": str(task.id),
                    "merchant_id": str(merchant_id),
                    "mode": "FULL",
                    "since": None,
                },
            )
        )
        return task.id


def _source_review_id(tenant_id: UUID, merchant_key: str, review_key: str) -> str:
    identity = f"{tenant_id}:{merchant_key}:{review_key}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
