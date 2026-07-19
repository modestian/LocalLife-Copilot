from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opensearchpy import OpenSearch
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.analytics import business_router as analytics_business_router
from app.api.analytics import compare_router as analytics_compare_router
from app.api.analytics import reviews_router as analytics_reviews_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.feedback import router as feedback_router
from app.api.health import router as health_router
from app.api.search import router as search_router
from app.api.users import router as users_router
from app.application.analytics import AnalyticsService
from app.application.auth import AuthService
from app.application.authorization import AuthorizationService
from app.core.api import install_api_contract
from app.core.config import Settings, get_settings
from app.core.readiness import ReadinessCheck, build_readiness_checks
from app.core.security import AccessTokenService, PasswordService
from app.etl.embeddings import BatchedEmbedder, HttpEmbeddingProvider
from app.infrastructure.db.repositories.auth import SQLAlchemyAuthRepository
from app.infrastructure.db.repositories.authorization import SQLAlchemyAuthorizationRepository
from app.infrastructure.db.repositories.sentiment import SQLAlchemySentimentRepository
from app.infrastructure.search.pipeline import HybridSearchService
from app.infrastructure.search.retrieval import OpenSearchDualRetriever
from app.infrastructure.search.service import HybridRecallService


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
        app.state.sentiment_repo = SQLAlchemySentimentRepository(session_factory)
        app.state.analytics_service = AnalyticsService(app.state.sentiment_repo)
        access_tokens = AccessTokenService(
            secret_key=app_settings.jwt_secret_key.get_secret_value(),
            issuer=app_settings.jwt_issuer,
            audience=app_settings.jwt_audience,
            ttl=timedelta(minutes=app_settings.access_token_ttl_minutes),
        )
        app.state.auth_service = AuthService(
            SQLAlchemyAuthRepository(session_factory),
            PasswordService(),
            access_tokens,
            refresh_ttl=timedelta(days=app_settings.refresh_token_ttl_days),
        )
        app.state.authorization_service = AuthorizationService(
            SQLAlchemyAuthorizationRepository(session_factory),
            access_tokens,
        )
        # FeedbackService will be wired when SQLAlchemyFeedbackRepository is ready;
        # tests inject InMemoryFeedbackRepository via app.state.feedback_service.
        redis_client = Redis.from_url(app_settings.redis_url, decode_responses=True)
        opensearch_client = OpenSearch(app_settings.opensearch_url)
        embedding_provider = HttpEmbeddingProvider(
            app_settings.model_gateway_embedding_url,
            model=app_settings.embedding_model,
            timeout_seconds=app_settings.dependency_timeout_seconds,
        )
        embedder = BatchedEmbedder(
            embedding_provider,
            dimension=app_settings.embedding_dimension,
            batch_size=app_settings.embedding_batch_size,
        )
        app.state.search_service = HybridSearchService(
            HybridRecallService(
                embedder,
                OpenSearchDualRetriever(
                    opensearch_client,
                    index=app_settings.opensearch_read_alias,
                ),
            )
        )
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
    app.include_router(analytics_router, prefix=app_settings.api_v1_prefix)
    app.include_router(analytics_compare_router, prefix=app_settings.api_v1_prefix)
    app.include_router(analytics_business_router, prefix=app_settings.api_v1_prefix)
    app.include_router(analytics_reviews_router, prefix=app_settings.api_v1_prefix)
    app.include_router(auth_router, prefix=app_settings.api_v1_prefix)
    app.include_router(feedback_router, prefix=app_settings.api_v1_prefix)
    app.include_router(users_router, prefix=app_settings.api_v1_prefix)
    app.include_router(search_router, prefix=app_settings.api_v1_prefix)
    return app


app = create_app()
