"""Reconcile/rebuild search storage and verify Redis read-through recovery."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings, get_settings
from app.etl.embeddings import BatchedEmbedder, HttpEmbeddingProvider
from app.infrastructure.cache.conversations import RedisConversationMemory
from app.infrastructure.db.models.conversations import Conversation, Message
from app.infrastructure.db.repositories.conversations import SQLAlchemyConversationRepository
from app.infrastructure.storage_recovery import OpenSearchRebuildStore, SQLAlchemyChunkFactSource
from app.operations.storage_recovery import IndexRebuildService, reconcile


def _adapters(settings: Settings):
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    facts = SQLAlchemyChunkFactSource(sessionmaker(engine, expire_on_commit=False))
    client = OpenSearch(settings.opensearch_url)
    embedder = BatchedEmbedder(
        HttpEmbeddingProvider(
            settings.model_gateway_embedding_url,
            model=settings.embedding_model,
            timeout_seconds=settings.embedding_request_timeout_seconds,
            max_attempts=settings.embedding_request_max_attempts,
        ),
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )
    projections = OpenSearchRebuildStore(
        client,
        embedder,
        read_alias=settings.opensearch_read_alias,
        write_alias=settings.opensearch_write_alias,
        embedding_dimension=settings.embedding_dimension,
    )
    return engine, client, facts, projections


def run_reconcile(settings: Settings, index: str, report_path: Path) -> bool:
    engine, client, facts, projections = _adapters(settings)
    try:
        report = reconcile(
            facts.list_indexable_chunks(),
            projections.list_projections(index),
        )
        _write_report(report_path, "reconcile", index, report.to_json())
        return report.consistent
    finally:
        client.close()
        engine.dispose()


def run_rebuild(
    settings: Settings, target_index: str, report_path: Path, *, allow_empty: bool
) -> None:
    engine, client, facts, projections = _adapters(settings)
    try:
        report = IndexRebuildService(facts, projections).rebuild(
            target_index, allow_empty=allow_empty
        )
        _write_report(report_path, "rebuild", target_index, report.to_json())
    finally:
        client.close()
        engine.dispose()


async def run_redis_drill(settings: Settings, report_path: Path, confirmation: str) -> bool:
    if confirmation != "FLUSH-TK-703-04":
        raise ValueError("Redis drill requires --confirm-flush FLUSH-TK-703-04")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        async with sessions() as session:
            candidate = (
                await session.execute(
                    select(Conversation.id, Conversation.owner_user_id)
                    .join(Message, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.status == "ACTIVE",
                        Conversation.memory_backend == "REDIS",
                    )
                    .order_by(Conversation.updated_at.desc())
                    .limit(1)
                )
            ).one_or_none()
        if candidate is None:
            raise RuntimeError("Redis drill needs an active conversation with durable messages")
        conversation_id, owner_user_id = candidate
        repository = SQLAlchemyConversationRepository(sessions)
        expected = await repository.list_recent_messages(conversation_id, owner_user_id, limit=20)
        await redis.flushdb()
        memory = RedisConversationMemory(repository, redis)
        restored = await memory.load(conversation_id, owner_user_id)
        cache_key = f"conversation:memory:v1:{conversation_id}"
        cache_repopulated = bool(await redis.exists(cache_key))
        passed = [message.id for message in restored] == [message.id for message in expected]
        passed = passed and cache_repopulated
        _write_report(
            report_path,
            "redis-fallback",
            cache_key,
            {
                "consistent": passed,
                "conversation_id": str(conversation_id),
                "mysql_message_count": len(expected),
                "restored_message_count": len(restored),
                "cache_repopulated": cache_repopulated,
            },
        )
        return passed
    finally:
        await redis.aclose()
        await engine.dispose()


def _write_report(path: Path, operation: str, target: str, result: dict[str, object]) -> None:
    payload = {
        "task_id": "TK-703-04",
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": operation,
        "target": target,
        **result,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    reconcile_parser = subparsers.add_parser("reconcile")
    reconcile_parser.add_argument("--index")
    reconcile_parser.add_argument("--report", type=Path, required=True)
    rebuild_parser = subparsers.add_parser("rebuild")
    rebuild_parser.add_argument("--target-index", required=True)
    rebuild_parser.add_argument("--report", type=Path, required=True)
    rebuild_parser.add_argument("--allow-empty", action="store_true")
    redis_parser = subparsers.add_parser("redis-fallback")
    redis_parser.add_argument("--report", type=Path, required=True)
    redis_parser.add_argument("--confirm-flush", required=True)
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "reconcile":
        index = args.index or settings.opensearch_read_alias
        return 0 if run_reconcile(settings, index, args.report) else 1
    if args.command == "rebuild":
        run_rebuild(settings, args.target_index, args.report, allow_empty=args.allow_empty)
        return 0
    passed = asyncio.run(run_redis_drill(settings, args.report, args.confirm_flush))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
