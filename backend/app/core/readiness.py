import asyncio
from collections.abc import Awaitable, Callable

from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ReadinessCheck = Callable[[], Awaitable[None]]


def build_readiness_checks(
    engine: AsyncEngine,
    redis_client: Redis,
    opensearch_client: OpenSearch,
) -> dict[str, ReadinessCheck]:
    async def mysql_check() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def redis_check() -> None:
        if not await redis_client.ping():
            raise ConnectionError("Redis ping returned false")

    async def opensearch_check() -> None:
        if not await asyncio.to_thread(opensearch_client.ping):
            raise ConnectionError("OpenSearch ping returned false")

    return {
        "mysql": mysql_check,
        "redis": redis_check,
        "opensearch": opensearch_check,
    }


async def run_readiness_checks(
    checks: dict[str, ReadinessCheck], timeout_seconds: float
) -> dict[str, str]:
    async def run_one(check: ReadinessCheck) -> str:
        try:
            await asyncio.wait_for(check(), timeout=timeout_seconds)
        except Exception:
            return "down"
        return "up"

    results = await asyncio.gather(*(run_one(check) for check in checks.values()))
    return dict(zip(checks, results, strict=True))
