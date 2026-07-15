import asyncio
from collections.abc import Awaitable, Callable
from urllib.request import Request, urlopen

from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

ReadinessCheck = Callable[[], Awaitable[None]]


def build_readiness_checks(
    engine: AsyncEngine,
    redis_client: Redis,
    opensearch_client: OpenSearch,
    model_gateway_health_url: str,
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

    def request_model_gateway() -> None:
        request = Request(model_gateway_health_url, headers={"User-Agent": "readiness-check"})
        with urlopen(request, timeout=2) as response:  # noqa: S310 - operator-configured URL
            if not 200 <= response.status < 400:
                raise ConnectionError("Model gateway health endpoint returned an error")

    async def model_gateway_check() -> None:
        await asyncio.to_thread(request_model_gateway)

    return {
        "mysql": mysql_check,
        "redis": redis_check,
        "opensearch": opensearch_check,
        "model_gateway": model_gateway_check,
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
