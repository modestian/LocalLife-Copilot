"""Database operations backing the API-spec completion endpoints."""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource
from app.infrastructure.db.models.feedback import Dataset, Feedback
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase
from app.infrastructure.db.models.operations import DataSource, FineTuningJob, Merchant, Review
from app.infrastructure.db.models.sentiment import ReviewAnalysis
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent

# English aspect code -> Chinese display label
_ASPECT_CN: dict[str, str] = {
    "taste": "口味",
    "portion": "分量",
    "price": "价格",
    "freshness": "新鲜度",
    "appearance": "卖相",
    "variety": "品种",
    "space": "空间",
    "quiet": "环境安静度",
    "decoration": "装修环境",
    "hygiene": "卫生",
    "location": "位置",
    "seating": "座位",
    "waiting_time": "等待时间",
    "attitude": "服务态度",
    "efficiency": "效率",
    "parking": "停车",
    "packing": "打包",
    "discount": "优惠",
    "set_meal": "套餐",
    "equipment": "设施",
    "overall": "整体体验",
}


def _translate_tags(tags: list) -> list[str]:
    """Translate English aspect codes to Chinese labels."""
    return [_ASPECT_CN.get(t, t) for t in tags if t]


class OperationsRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_data_source(
        self,
        *,
        knowledge_base_id: UUID,
        name: str,
        source_type: str,
        config: dict[str, object],
        created_by: UUID,
    ) -> DataSource:
        async with self._session_factory() as session, session.begin():
            knowledge_base = await session.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.id == knowledge_base_id,
                    KnowledgeBase.deleted_at.is_(None),
                    KnowledgeBase.status != "DELETED",
                )
            )
            if knowledge_base is None:
                raise LookupError("knowledge base not found")
            row = DataSource(
                knowledge_base_id=knowledge_base_id,
                name=name,
                source_type=source_type,
                config_json=config,
                created_by=created_by,
            )
            session.add(row)
            await session.flush()
            return row

    async def get_data_source(self, data_source_id: UUID) -> DataSource | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DataSource).where(
                    DataSource.id == data_source_id,
                    DataSource.status == "ACTIVE",
                )
            )

    async def ingest_data_source(self, data_source_id: UUID) -> tuple[DataSource, UUID, UUID]:
        async with self._session_factory() as session, session.begin():
            source = await session.scalar(
                select(DataSource)
                .where(DataSource.id == data_source_id, DataSource.status == "ACTIVE")
                .with_for_update()
            )
            if source is None:
                raise LookupError("data source not found")
            config = source.config_json
            uri = str(config.get("source_uri") or "").strip()
            sha256 = str(config.get("source_sha256") or "").lower()
            size = int(config.get("source_size_bytes") or 0)
            if not uri or len(sha256) != 64 or size <= 0:
                raise ValueError(
                    "source_uri, source_sha256 and positive source_size_bytes are required"
                )
            document = await session.scalar(
                select(Document).where(
                    Document.knowledge_base_id == source.knowledge_base_id,
                    Document.source_type == "DATA_SOURCE",
                    Document.source_key == str(source.id),
                )
            )
            if document is None:
                document = Document(
                    knowledge_base_id=source.knowledge_base_id,
                    source_type="DATA_SOURCE",
                    source_key=str(source.id),
                    display_name=source.name,
                    mime_type=str(config.get("mime_type") or "text/csv"),
                )
                session.add(document)
                await session.flush()
            current = await session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.file_sha256 == sha256,
                    DocumentVersion.is_current.is_(True),
                )
            )
            if current is None:
                await session.execute(
                    DocumentVersion.__table__.update()
                    .where(DocumentVersion.document_id == document.id)
                    .values(is_current=False)
                )
                version_no = document.current_version_no + 1
                session.add(
                    DocumentVersion(
                        document_id=document.id,
                        version_no=version_no,
                        file_uri=uri,
                        file_sha256=sha256,
                        file_size=size,
                        parser_name=str(
                            config.get("parser_name") or Path(uri).suffix.lstrip(".") or "csv"
                        ),
                        parser_version=str(config.get("parser_version") or "1"),
                        cleaning_config_json=dict(config.get("cleaning_config") or {"steps": []}),
                        splitter_config_json=dict(
                            config.get("splitter_config")
                            or {"strategy": "recursive", "chunk_size": 500, "chunk_overlap": 80}
                        ),
                        is_current=True,
                    )
                )
                document.current_version_no = version_no
            task = AsyncTask(task_type="INGEST", resource_type="DOCUMENT", resource_id=document.id)
            session.add(task)
            await session.flush()
            session.add(
                OutboxEvent(
                    aggregate_type="ASYNC_TASK",
                    aggregate_id=task.id,
                    event_type="knowledge.ingest",
                    event_version=1,
                    payload_json={"task_id": str(task.id), "data_source_id": str(source.id)},
                )
            )
            await session.flush()
            return source, document.id, task.id

    async def clone_knowledge_base(
        self, source_id: UUID, *, name: str, owner_id: UUID
    ) -> tuple[KnowledgeBase, list[UUID]]:
        async with self._session_factory() as session, session.begin():
            source = await session.scalar(
                select(KnowledgeBase).where(
                    KnowledgeBase.id == source_id,
                    KnowledgeBase.deleted_at.is_(None),
                    KnowledgeBase.status != "DELETED",
                )
            )
            if source is None:
                raise LookupError("knowledge base not found")
            clone = KnowledgeBase(
                tenant_id=source.tenant_id,
                department_id=source.department_id,
                owner_id=owner_id,
                name=name,
                normalized_name=" ".join(name.casefold().split()),
                description=source.description,
                embedding_model_version_id=source.embedding_model_version_id,
                chunk_size=source.chunk_size,
                chunk_overlap=source.chunk_overlap,
            )
            session.add(clone)
            await session.flush()
            task_ids: list[UUID] = []
            documents = (
                await session.scalars(
                    select(Document).where(
                        Document.knowledge_base_id == source_id,
                        Document.deleted_at.is_(None),
                        Document.status != "DELETED",
                    )
                )
            ).all()
            for document in documents:
                copied = Document(
                    knowledge_base_id=clone.id,
                    source_type=document.source_type,
                    source_key=document.source_key,
                    display_name=document.display_name,
                    mime_type=document.mime_type,
                    status="UPLOADED",
                )
                session.add(copied)
                await session.flush()
                version = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == document.id,
                        DocumentVersion.is_current.is_(True),
                    )
                )
                if version is not None:
                    copied.current_version_no = 1
                    session.add(
                        DocumentVersion(
                            document_id=copied.id,
                            version_no=1,
                            file_uri=version.file_uri,
                            file_sha256=version.file_sha256,
                            file_size=version.file_size,
                            parser_name=version.parser_name,
                            parser_version=version.parser_version,
                            cleaning_config_json=version.cleaning_config_json,
                            splitter_config_json=version.splitter_config_json,
                            is_current=True,
                        )
                    )
                    task = AsyncTask(
                        task_type="INGEST", resource_type="DOCUMENT", resource_id=copied.id
                    )
                    session.add(task)
                    await session.flush()
                    session.add(
                        OutboxEvent(
                            aggregate_type="ASYNC_TASK",
                            aggregate_id=task.id,
                            event_type="knowledge.ingest",
                            event_version=1,
                            payload_json={"task_id": str(task.id), "cloned_from": str(document.id)},
                        )
                    )
                    task_ids.append(task.id)
            await session.flush()
            return clone, task_ids

    async def preview_document(
        self,
        document_id: UUID,
        *,
        version_no: int | None = None,
        query: str | None,
        chunk_page: int = 1,
        chunk_page_size: int = 20,
    ) -> dict[str, object] | None:
        async with self._session_factory() as session:
            document = await session.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.deleted_at.is_(None),
                    Document.status != "DELETED",
                )
            )
            if document is None:
                return None

            # Determine which version to preview
            version = None
            if version_no is not None:
                version = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.version_no == version_no,
                    )
                )
            if version is None:
                version = await session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.is_current.is_(True),
                    )
                )

            # Fetch original content (file URI reference)
            original_content = ""
            original_truncated = False
            if version is not None and version.file_uri:
                try:
                    path = Path(version.file_uri)
                    if path.exists():
                        raw = path.read_text(encoding="utf-8", errors="replace")
                        if len(raw) > 100_000:
                            original_content = raw[:100_000]
                            original_truncated = True
                        else:
                            original_content = raw
                except Exception:
                    original_content = ""

            # Fetch chunks with pagination
            chunks: list[Chunk] = []
            chunk_total = 0
            if version is not None:
                chunk_total = (
                    await session.scalar(
                        select(func.count())
                        .select_from(Chunk)
                        .where(Chunk.document_version_id == version.id)
                    )
                ) or 0
                offset = (chunk_page - 1) * chunk_page_size
                chunks = list(
                    (
                        await session.scalars(
                            select(Chunk)
                            .where(Chunk.document_version_id == version.id)
                            .order_by(Chunk.chunk_no)
                            .offset(offset)
                            .limit(chunk_page_size)
                        )
                    ).all()
                )

            needle = (query or "").strip()
            items = []
            for chunk in chunks:
                content = chunk.content
                highlighted = content
                if needle:
                    highlighted = content.replace(needle, f"<mark>{needle}</mark>")
                items.append(
                    {
                        "id": str(chunk.id),
                        "chunk_no": chunk.chunk_no,
                        "content": content,
                        "highlighted_content": highlighted,
                        "token_count": chunk.token_count,
                        "page_number": chunk.page_number,
                        "metadata": chunk.metadata_json,
                    }
                )
            return {
                "document_id": str(document.id),
                "display_name": document.display_name,
                "version_no": version.version_no if version else 0,
                "source_uri": version.file_uri if version else None,
                "query": needle or None,
                "original_content": original_content,
                "original_truncated": original_truncated,
                "chunks": items,
                "chunk_page": chunk_page,
                "chunk_page_size": chunk_page_size,
                "chunk_total": chunk_total,
            }

    async def list_merchants(
        self,
        *,
        category: str | None,
        min_price: int | None,
        max_price: int | None,
        business_status: str | None,
        longitude: float | None,
        latitude: float | None,
        radius_m: int | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Merchant], int]:
        filters = []
        if category:
            filters.append(Merchant.category == category)
        if min_price is not None:
            filters.append(Merchant.avg_price_cent >= min_price)
        if max_price is not None:
            filters.append(Merchant.avg_price_cent <= max_price)
        if business_status:
            filters.append(Merchant.business_status == business_status)
        async with self._session_factory() as session:
            candidates = list(
                (
                    await session.scalars(
                        select(Merchant).where(*filters).order_by(Merchant.created_at.desc())
                    )
                ).all()
            )
        if longitude is not None and latitude is not None and radius_m is not None:
            candidates = [
                row
                for row in candidates
                if _distance_m(latitude, longitude, float(row.latitude), float(row.longitude))
                <= radius_m
            ]
        return candidates[offset : offset + limit], len(candidates)

    async def search_merchants_directory(
        self,
        *,
        keyword: str | None = None,
        limit: int = 50,
    ) -> list[Merchant]:
        """Lightweight merchant directory for all authenticated users (no resource scoping)."""
        async with self._session_factory() as session:
            stmt = select(Merchant).order_by(Merchant.name)
            if keyword:
                pattern = f"%{keyword}%"
                stmt = stmt.where(Merchant.name.like(pattern) | Merchant.category.like(pattern))
            rows = list((await session.scalars(stmt.limit(limit))).all())
        return rows

    async def get_merchant(self, merchant_id: UUID) -> tuple[Merchant, dict[str, object]] | None:
        async with self._session_factory() as session:
            merchant = await session.get(Merchant, merchant_id)
            if merchant is None:
                return None
            counts = (
                await session.execute(
                    select(
                        func.count(ReviewAnalysis.id),
                        func.sum(ReviewAnalysis.sentiment == "POSITIVE"),
                        func.sum(ReviewAnalysis.sentiment == "NEGATIVE"),
                        func.max(ReviewAnalysis.updated_at),
                    ).where(ReviewAnalysis.merchant_id == str(merchant_id))
                )
            ).one()
            total = int(counts[0] or 0)
            return merchant, {
                "review_count": total,
                "positive_rate": round(float(counts[1] or 0) / total, 4) if total else 0,
                "negative_rate": round(float(counts[2] or 0) / total, 4) if total else 0,
                "analysis_updated_at": counts[3],
            }

    async def list_reviews(
        self,
        merchant_id: UUID,
        *,
        sentiment: str | None,
        tag: str | None,
        start_at: datetime | None,
        end_at: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        filters = [Review.merchant_id == merchant_id, Review.status == "PUBLISHED"]
        if start_at:
            filters.append(Review.reviewed_at >= start_at)
        if end_at:
            filters.append(Review.reviewed_at < end_at)
        analysis_filters = [ReviewAnalysis.merchant_id == str(merchant_id)]
        if start_at:
            analysis_filters.append(ReviewAnalysis.review_date >= start_at)
        if end_at:
            analysis_filters.append(ReviewAnalysis.review_date < end_at)
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(Review).where(*filters).order_by(Review.reviewed_at.desc())
                    )
                ).all()
            )
            analysis_rows = list(
                (
                    await session.scalars(
                        select(ReviewAnalysis)
                        .where(*analysis_filters)
                        .order_by(ReviewAnalysis.review_date.desc())
                    )
                ).all()
            )
        # Merge both sources: user-submitted reviews + ETL-imported analyses
        # Build a content-based lookup to avoid duplicates when a user review
        # has been analyzed and written to review_analyses.
        items: list[dict[str, object]] = []
        user_review_texts: set[str] = set()
        analysis_by_text: dict[str, object] = {}
        for row in analysis_rows:
            analysis_by_text.setdefault(row.review_text, row)

        for row in rows:
            user_review_texts.add(row.content)
            # Enrich with sentiment from analysis if available
            matched = analysis_by_text.get(row.content)
            if matched is not None:
                item_sentiment = matched.sentiment
                item_confidence = matched.confidence
                item_tags = _translate_tags(
                    json.loads(matched.aspect_labels)
                    if isinstance(matched.aspect_labels, str)
                    else (matched.aspect_labels or [])
                )
            else:
                item_sentiment = None
                item_confidence = None
                item_tags = _translate_tags(row.tags_json or [])
            items.append(
                {
                    "id": str(row.id),
                    "content": row.content,
                    "rating": float(row.rating) if row.rating is not None else None,
                    "author_ref": row.author_ref,
                    "reviewed_at": row.reviewed_at,
                    "tags": item_tags,
                    "sentiment": item_sentiment,
                    "confidence": item_confidence,
                }
            )

        # Only add analysis entries that don't correspond to a user review
        for row in analysis_rows:
            if row.review_text in user_review_texts:
                continue
            items.append(
                {
                    "id": str(row.id),
                    "content": row.review_text,
                    "rating": None,
                    "author_ref": None,
                    "reviewed_at": row.review_date,
                    "tags": _translate_tags(
                        json.loads(row.aspect_labels)
                        if isinstance(row.aspect_labels, str)
                        else (row.aspect_labels or [])
                    ),
                    "sentiment": row.sentiment,
                    "confidence": row.confidence,
                }
            )
        # Sort merged list by date descending
        items.sort(
            key=lambda x: x["reviewed_at"] or datetime.min.replace(tzinfo=None),
            reverse=True,
        )
        if sentiment:
            items = [item for item in items if item["sentiment"] == sentiment]
        if tag:
            items = [item for item in items if tag in item["tags"]]
        return items[offset : offset + limit], len(items)

    async def create_analysis_job(
        self, merchant_id: UUID, *, mode: str, since: datetime | None
    ) -> UUID:
        async with self._session_factory() as session, session.begin():
            if await session.get(Merchant, merchant_id) is None:
                raise LookupError("merchant not found")
            task = AsyncTask(
                task_type="MERCHANT_ANALYSIS",
                resource_type="MERCHANT",
                resource_id=merchant_id,
                result_json={
                    "mode": mode,
                    "since": since.isoformat() if since else None,
                },
            )
            session.add(task)
            await session.flush()
            session.add(
                OutboxEvent(
                    aggregate_type="ASYNC_TASK",
                    aggregate_id=task.id,
                    event_type="merchant.analysis",
                    event_version=1,
                    payload_json={
                        "task_id": str(task.id),
                        "merchant_id": str(merchant_id),
                        "mode": mode,
                        "since": since.isoformat() if since else None,
                    },
                )
            )
            await session.flush()
            return task.id

    async def create_fine_tuning_job(
        self,
        *,
        dataset_id: UUID,
        task_type: str,
        base_model_ref: str,
        method: str,
        hyperparameters: dict[str, object],
        created_by: UUID,
    ) -> FineTuningJob:
        canonical = json.dumps(hyperparameters, sort_keys=True, separators=(",", ":"))
        spec_hash = hashlib.sha256(canonical.encode()).hexdigest()
        async with self._session_factory() as session, session.begin():
            dataset = await session.get(Dataset, dataset_id)
            if dataset is None:
                raise LookupError("dataset not found")
            if dataset.status != "READY":
                raise ValueError("only READY datasets can be used for training")
            task_id = uuid7()
            task = AsyncTask(
                id=task_id,
                task_type="LORA_TRAINING",
                resource_type="FINE_TUNING_JOB",
                resource_id=uuid7(),
                max_attempts=1,
            )
            job = FineTuningJob(
                id=task.resource_id,
                dataset_id=dataset_id,
                async_task_id=task_id,
                task_type=task_type,
                base_model_ref=base_model_ref,
                method=method,
                hyperparameters_json=hyperparameters,
                hyperparameter_hash=spec_hash,
                seed=int(hyperparameters.get("seed") or 42),
                created_by=created_by,
            )
            session.add_all([task, job])
            await session.flush()
            session.add(
                OutboxEvent(
                    aggregate_type="ASYNC_TASK",
                    aggregate_id=task.id,
                    event_type="fine_tuning.train",
                    event_version=1,
                    payload_json={"task_id": str(task.id), "job_id": str(job.id)},
                )
            )
            await session.flush()
            return job

    async def get_fine_tuning_job(self, job_id: UUID) -> FineTuningJob | None:
        async with self._session_factory() as session:
            return await session.get(FineTuningJob, job_id)

    async def cancel_fine_tuning_job(self, job_id: UUID) -> FineTuningJob | None:
        async with self._session_factory() as session, session.begin():
            job = await session.scalar(
                select(FineTuningJob).where(FineTuningJob.id == job_id).with_for_update()
            )
            if job is None:
                return None
            if job.status not in {"PENDING", "RUNNING"}:
                raise ValueError("job is not cancellable")
            task = await session.get(AsyncTask, job.async_task_id)
            job.status = "CANCELLED"
            job.completed_at = utc_now()
            if task is not None:
                task.status = "CANCELLED" if task.status == "PENDING" else "CANCEL_REQUESTED"
            await session.flush()
            return job

    async def evaluate_fine_tuning_job(self, job_id: UUID, benchmark: str) -> UUID:
        async with self._session_factory() as session, session.begin():
            job = await session.get(FineTuningJob, job_id)
            if job is None:
                raise LookupError("fine-tuning job not found")
            if job.status != "SUCCEEDED" or not job.artifact_uri:
                raise ValueError("only successful jobs with artifacts can be evaluated")
            task = AsyncTask(
                task_type="MODEL_EVALUATION",
                resource_type="FINE_TUNING_JOB",
                resource_id=job.id,
                max_attempts=1,
                result_json={"benchmark": benchmark},
            )
            session.add(task)
            await session.flush()
            session.add(
                OutboxEvent(
                    aggregate_type="ASYNC_TASK",
                    aggregate_id=task.id,
                    event_type="fine_tuning.evaluate",
                    event_version=1,
                    payload_json={
                        "task_id": str(task.id),
                        "job_id": str(job.id),
                        "benchmark": benchmark,
                    },
                )
            )
            await session.flush()
            return task.id

    async def list_moderation_cases(
        self, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[Feedback], int]:
        filters = []
        if status:
            filters.append(Feedback.review_status == status)
        async with self._session_factory() as session:
            total = int(await session.scalar(select(func.count(Feedback.id)).where(*filters)) or 0)
            rows = list(
                (
                    await session.scalars(
                        select(Feedback)
                        .where(*filters)
                        .order_by(Feedback.updated_at.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                ).all()
            )
            return rows, total

    async def decide_moderation_case(self, case_id: UUID, decision: str) -> Feedback | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(Feedback, case_id)
            if row is None:
                return None
            row.review_status = {
                "APPROVE": "APPROVED",
                "REJECT": "REJECTED",
                "ESCALATE": "PENDING_REVIEW",
            }[decision]
            row.version += 1
            await session.flush()
            return row

    async def analytics_overview(self, start_at: datetime | None, end_at: datetime | None):
        message_filters = []
        conversation_filters = []
        feedback_filters = []
        if start_at:
            message_filters.append(Message.created_at >= start_at)
            conversation_filters.append(Conversation.created_at >= start_at)
            feedback_filters.append(Feedback.created_at >= start_at)
        if end_at:
            message_filters.append(Message.created_at < end_at)
            conversation_filters.append(Conversation.created_at < end_at)
            feedback_filters.append(Feedback.created_at < end_at)
        async with self._session_factory() as session:
            conversations = int(
                await session.scalar(
                    select(func.count(Conversation.id)).where(*conversation_filters)
                )
                or 0
            )
            active_users = int(
                await session.scalar(
                    select(func.count(func.distinct(Conversation.owner_user_id))).where(
                        *conversation_filters
                    )
                )
                or 0
            )
            messages = int(
                await session.scalar(select(func.count(Message.id)).where(*message_filters)) or 0
            )
            assistant_messages = int(
                await session.scalar(
                    select(func.count(Message.id)).where(
                        *message_filters, Message.role == "ASSISTANT"
                    )
                )
                or 0
            )
            sourced_messages = int(
                await session.scalar(
                    select(func.count(func.distinct(MessageSource.message_id)))
                    .join(Message, Message.id == MessageSource.message_id)
                    .where(*message_filters)
                )
                or 0
            )
            positive_feedback = int(
                await session.scalar(
                    select(func.count(Feedback.id)).where(*feedback_filters, Feedback.rating == 1)
                )
                or 0
            )
            feedback_count = int(
                await session.scalar(select(func.count(Feedback.id)).where(*feedback_filters)) or 0
            )
        return {
            "conversation_count": conversations,
            "message_count": messages,
            "active_user_count": active_users,
            "retrieval_success_rate": (
                round(sourced_messages / assistant_messages, 4) if assistant_messages else 0
            ),
            "positive_feedback_rate": (
                round(positive_feedback / feedback_count, 4) if feedback_count else 0
            ),
            "average_response_time_ms": None,
        }

    # ------------------------------------------------------------------
    # User-submitted reviews
    # ------------------------------------------------------------------

    async def create_user_review(
        self,
        *,
        merchant_id: UUID,
        user_id: UUID,
        content: str,
        rating: float,
        author_name: str | None = None,
    ) -> Review:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        async with self._session_factory() as session, session.begin():
            merchant = await session.scalar(select(Merchant).where(Merchant.id == merchant_id))
            if merchant is None:
                raise LookupError("merchant not found")
            # Idempotency: same user + same merchant + same content hash
            existing = await session.scalar(
                select(Review).where(
                    Review.merchant_id == merchant_id,
                    Review.user_id == user_id,
                    Review.content_hash == content_hash,
                    Review.status != "DELETED",
                )
            )
            if existing is not None:
                return existing
            review = Review(
                id=uuid7(),
                merchant_id=merchant_id,
                user_id=user_id,
                author_ref=author_name,
                content=content,
                content_hash=content_hash,
                rating=rating,
                reviewed_at=utc_now(),
                source_type="USER_SUBMITTED",
                source_review_id=None,
                status="PENDING",
            )
            session.add(review)
            await session.flush()
            return review

    async def list_user_reviews(
        self,
        user_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Review], int]:
        async with self._session_factory() as session:
            base = select(Review).where(Review.user_id == user_id)
            total = int(
                await session.scalar(select(func.count()).select_from(base.subquery())) or 0
            )
            rows = list(
                (
                    await session.scalars(
                        base.order_by(Review.created_at.desc()).limit(limit).offset(offset)
                    )
                ).all()
            )
        return rows, total

    async def moderate_user_review(
        self,
        review_id: UUID,
        *,
        decision: str,
        reason: str,
        moderator_id: UUID,
    ) -> Review:
        async with self._session_factory() as session, session.begin():
            review = await session.scalar(
                select(Review).where(Review.id == review_id).with_for_update()
            )
            if review is None:
                raise LookupError("review not found")
            if review.status != "PENDING":
                raise ValueError(f"review is not pending, current status: {review.status}")
            review.status = "PUBLISHED" if decision == "APPROVE" else "REJECTED"
            await session.flush()
            return review

    async def list_pending_reviews(
        self,
        *,
        status: str = "PENDING",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Review], int]:
        """List reviews by status for admin moderation."""
        async with self._session_factory() as session:
            base = select(Review).where(Review.status == status)
            total = int(
                await session.scalar(select(func.count()).select_from(base.subquery())) or 0
            )
            rows = list(
                (
                    await session.scalars(
                        base.order_by(Review.created_at.asc()).limit(limit).offset(offset)
                    )
                ).all()
            )
        return rows, total

    async def create_review_analysis(
        self,
        *,
        merchant_id: str,
        review_text: str,
        sentiment: str,
        confidence: float,
        model_version: str,
        aspect_labels: list[str],
        negative_reasons: list[str],
        review_date: datetime | None,
    ) -> ReviewAnalysis:
        """Persist sentiment analysis result for a user-submitted review."""
        async with self._session_factory() as session, session.begin():
            analysis = ReviewAnalysis(
                id=uuid7(),
                merchant_id=merchant_id,
                review_text=review_text,
                sentiment=sentiment,
                confidence=confidence,
                model_version=model_version,
                aspect_labels=json.dumps(aspect_labels, ensure_ascii=False),
                negative_reasons=json.dumps(negative_reasons, ensure_ascii=False),
                review_date=review_date,
            )
            session.add(analysis)
            await session.flush()
            return analysis


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))
