import os

import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.conversations import MessageInput, MessageRole, SourceInput
from app.application.knowledge import (
    DocumentInput,
    DocumentVersionInput,
    KnowledgeBaseInput,
)
from app.core.config import Settings
from app.core.ids import uuid7
from app.infrastructure.cache.conversations import RedisConversationMemory
from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource
from app.infrastructure.db.models.identity import Department, User
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent
from app.infrastructure.db.repositories.conversations import SQLAlchemyConversationRepository
from app.infrastructure.db.repositories.knowledge import SQLAlchemyKnowledgeRepository
from app.infrastructure.db.repositories.tasks import SQLAlchemyTaskRepository

pytestmark = pytest.mark.skipif(
    os.getenv("ST102_MYSQL_INTEGRATION") != "1",
    reason="set ST102_MYSQL_INTEGRATION=1 with MySQL and Redis available",
)


@pytest.mark.asyncio
async def test_st102_metadata_task_and_conversation_runtime_against_mysql() -> None:
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    knowledge = SQLAlchemyKnowledgeRepository(session_factory)
    tasks = SQLAlchemyTaskRepository(session_factory)
    conversations = SQLAlchemyConversationRepository(session_factory)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    suffix = uuid7().hex
    department_id = uuid7()
    user_id = uuid7()
    knowledge_base_id = None
    document_id = None
    conversation_id = None
    task_id = None
    try:
        async with session_factory() as session, session.begin():
            session.add(
                Department(
                    id=department_id,
                    code=f"st102-{suffix}",
                    name="ST-102 integration tenant",
                    path=f"/st102/{suffix}",
                )
            )
            session.add(
                User(
                    id=user_id,
                    department_id=department_id,
                    username=f"st102-{suffix}",
                    normalized_username=f"st102-{suffix}",
                    password_hash="integration-test-only",
                    display_name="ST-102 integration user",
                )
            )

        knowledge_base = await knowledge.create_knowledge_base(
            KnowledgeBaseInput(
                tenant_id=department_id,
                department_id=department_id,
                owner_id=user_id,
                name=f"ST-102 {suffix}",
                embedding_model_version_id=uuid7(),
            )
        )
        knowledge_base_id = knowledge_base.id
        assert knowledge_base.tenant_id == department_id
        assert [row.id for row in await knowledge.list_knowledge_bases(department_id)] == [
            knowledge_base.id
        ]

        document = await knowledge.create_document(
            DocumentInput(
                knowledge_base_id=knowledge_base.id,
                source_type="FILE",
                source_key=f"source-{suffix}",
                display_name="menu.md",
                mime_type="text/markdown",
            )
        )
        document_id = document.id
        repeated_document = await knowledge.create_document(
            DocumentInput(
                knowledge_base_id=knowledge_base.id,
                source_type="FILE",
                source_key=f"source-{suffix}",
                display_name="renamed.md",
                mime_type="text/markdown",
            )
        )
        assert repeated_document.id == document.id

        first_version = await knowledge.create_document_version_idempotent(
            DocumentVersionInput(
                document_id=document.id,
                file_uri=f"file:///tmp/{suffix}-v1.md",
                file_sha256="a" * 64,
                file_size=10,
                parser_name="markdown",
                parser_version="1",
                cleaning_config={},
                splitter_config={"strategy": "recursive"},
            )
        )
        second_input = DocumentVersionInput(
            document_id=document.id,
            file_uri=f"file:///tmp/{suffix}-v2.md",
            file_sha256="b" * 64,
            file_size=12,
            parser_name="markdown",
            parser_version="1",
            cleaning_config={},
            splitter_config={"strategy": "recursive"},
        )
        second_version = await knowledge.create_document_version_idempotent(second_input)
        assert (await knowledge.create_document_version_idempotent(second_input)).id == (
            second_version.id
        )
        assert (await knowledge.rollback_document(document.id, 1)).current_version_no == 1

        chunk_id = uuid7()
        async with session_factory() as session, session.begin():
            session.add(
                Chunk(
                    id=chunk_id,
                    document_version_id=first_version.id,
                    chunk_no=1,
                    content="quoted source",
                    content_hash="c" * 64,
                    token_count=2,
                    metadata_json={},
                    embedding_model_version_id=uuid7(),
                    opensearch_document_id=f"st102-{suffix}",
                )
            )

        conversation = await conversations.create_conversation(user_id, title="restore me")
        conversation_id = conversation.id
        message = await conversations.append_message(
            conversation.id,
            user_id,
            MessageInput(
                role=MessageRole.ASSISTANT,
                content="answer",
                sources=(
                    SourceInput(
                        chunk_id=chunk_id,
                        rank_no=1,
                        source_location_snapshot="menu.md#1",
                        content_snapshot="quoted source",
                    ),
                ),
            ),
        )
        memory = RedisConversationMemory(
            conversations,
            redis,
            key_prefix=f"st102:integration:{suffix}",
        )
        await memory.invalidate(conversation.id)
        restored = await memory.load(conversation.id, user_id)
        assert restored[0].id == message.id
        assert restored[0].sources[0].content_snapshot == "quoted source"

        task_id = await tasks.delete_document_with_outbox(document.id)
        assert task_id is not None
        async with session_factory() as session:
            deleted_document = await session.get(Document, document.id)
            event = await session.scalar(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == task_id)
            )
            assert deleted_document is not None
            assert deleted_document.status == "DELETED"
            assert deleted_document.deleted_at is not None
            assert event is not None
            assert event.payload_json == {"task_id": str(task_id)}
        assert await knowledge.get_task_document_knowledge_base_id(document.id) == knowledge_base.id
    finally:
        await redis.aclose()
        async with session_factory() as session, session.begin():
            if conversation_id is not None:
                message_ids = select(Message.id).where(Message.conversation_id == conversation_id)
                await session.execute(
                    delete(MessageSource).where(MessageSource.message_id.in_(message_ids))
                )
                await session.execute(
                    delete(Message).where(Message.conversation_id == conversation_id)
                )
                await session.execute(
                    delete(Conversation).where(Conversation.id == conversation_id)
                )
            if document_id is not None:
                version_ids = select(DocumentVersion.id).where(
                    DocumentVersion.document_id == document_id
                )
                await session.execute(
                    delete(Chunk).where(Chunk.document_version_id.in_(version_ids))
                )
            if task_id is not None:
                await session.execute(
                    delete(OutboxEvent).where(OutboxEvent.aggregate_id == task_id)
                )
                await session.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            if document_id is not None:
                await session.execute(
                    delete(DocumentVersion).where(DocumentVersion.document_id == document_id)
                )
                await session.execute(delete(Document).where(Document.id == document_id))
            if knowledge_base_id is not None:
                await session.execute(
                    delete(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
                )
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(delete(Department).where(Department.id == department_id))
        await engine.dispose()
