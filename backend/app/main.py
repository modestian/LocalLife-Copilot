from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.application.auth import AuthService
from app.core.api import install_api_contract
from app.core.config import Settings, get_settings
from app.core.readiness import ReadinessCheck, build_readiness_checks
from app.core.security import AccessTokenService, PasswordService
from app.infrastructure.db.repositories.auth import SQLAlchemyAuthRepository


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
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        app.state.auth_service = AuthService(
            SQLAlchemyAuthRepository(session_factory),
            PasswordService(),
            AccessTokenService(
                secret_key=app_settings.jwt_secret_key.get_secret_value(),
                issuer=app_settings.jwt_issuer,
                audience=app_settings.jwt_audience,
                ttl=timedelta(minutes=app_settings.access_token_ttl_minutes),
            ),
            refresh_ttl=timedelta(days=app_settings.refresh_token_ttl_days),
        )
        redis_client = Redis.from_url(app_settings.redis_url, decode_responses=True)
        opensearch_client = OpenSearch(app_settings.opensearch_url)
        app.state.readiness_checks = build_readiness_checks(
            engine,
            redis_client,
            opensearch_client,
            app_settings.model_gateway_health_url,
        )
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()
            opensearch_client.close()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    install_api_contract(app, app_settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router, prefix=app_settings.api_v1_prefix)
    return app


app = create_app()
