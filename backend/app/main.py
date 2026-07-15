from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.readiness import ReadinessCheck, build_readiness_checks


def create_app(
    readiness_checks: dict[str, ReadinessCheck] | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if readiness_checks is not None:
            app.state.readiness_checks = readiness_checks
            yield
            return

        engine = create_async_engine(app_settings.database_url, pool_pre_ping=True)
        redis_client = Redis.from_url(app_settings.redis_url, decode_responses=True)
        opensearch_client = OpenSearch(app_settings.opensearch_url)
        app.state.readiness_checks = build_readiness_checks(engine, redis_client, opensearch_client)
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()
            opensearch_client.close()

    app = FastAPI(title=app_settings.app_name, version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    return app


app = create_app()
