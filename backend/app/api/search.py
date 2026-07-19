"""Permission-safe hybrid search REST endpoint."""

import math
import time
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import AuthorizationDenied
from app.core.api import success_response
from app.core.errors import AppError
from app.etl.embeddings import EmbeddingError
from app.infrastructure.search.pipeline import HybridSearchService
from app.infrastructure.search.ranking import RankedHit, RankingConfig
from app.infrastructure.search.retrieval import BusinessSearchFilters, SearchBackendError
from app.infrastructure.search.scope import scope_from_principal

router = APIRouter(prefix="/search", tags=["search"])

CategoryValue = Annotated[str, Field(min_length=1, max_length=128)]


class SearchFiltersDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category: list[CategoryValue] = Field(default_factory=list, max_length=20)
    price_cent_lte: int | None = Field(default=None, ge=0)
    distance_meter_lte: int | None = Field(default=None, ge=0)
    open_now: bool | None = None
    document_type: list[Literal["review", "merchant"]] = Field(default_factory=list, max_length=2)


class SearchRequestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=2000)
    knowledge_base_ids: list[UUID] = Field(min_length=1, max_length=50)
    top_k: int = Field(default=10, ge=1, le=100)
    vector_weight: float = Field(default=0.6, ge=0, le=1)
    keyword_weight: float = Field(default=0.4, ge=0, le=1)
    rerank: bool = True
    filters: SearchFiltersDTO = Field(default_factory=SearchFiltersDTO)

    @model_validator(mode="after")
    def validate_weights(self) -> "SearchRequestDTO":
        if not math.isclose(self.vector_weight + self.keyword_weight, 1.0, rel_tol=0, abs_tol=1e-6):
            raise ValueError("vector_weight and keyword_weight must sum to 1")
        return self


def get_search_service(request: Request) -> HybridSearchService:
    service = getattr(request.app.state, "search_service", None)
    if service is None:
        raise AppError(503, "SEARCH_UNAVAILABLE", "搜索服务暂不可用")
    return service


SearchServiceDependency = Annotated[HybridSearchService, Depends(get_search_service)]


@router.post("")
async def hybrid_search(
    request: Request,
    body: SearchRequestDTO,
    principal: CurrentPrincipal,
    service: SearchServiceDependency,
) -> dict[str, Any]:
    """Search only the tenant and knowledge bases authorized by server-side grants."""
    tenant_id = principal.department_id
    if tenant_id is None:
        raise AppError(403, "TENANT_CONTEXT_REQUIRED", "当前账号缺少可检索的租户上下文")
    try:
        scope = scope_from_principal(
            principal,
            tenant_id=tenant_id,
            requested_knowledge_base_ids=body.knowledge_base_ids,
        )
    except AuthorizationDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有知识库检索权限") from exc

    filters = BusinessSearchFilters(
        categories=tuple(dict.fromkeys(value.strip() for value in body.filters.category)),
        price_cent_lte=body.filters.price_cent_lte,
        distance_meter_lte=body.filters.distance_meter_lte,
        open_now=body.filters.open_now,
        document_types=tuple(dict.fromkeys(body.filters.document_type)),
    )
    config = RankingConfig(
        method="weighted",
        bm25_weight=body.keyword_weight,
        vector_weight=body.vector_weight,
        minimum_score=request.app.state.settings.search_minimum_score,
        minimum_evidence=min(2, body.top_k),
    )

    started = time.perf_counter()
    try:
        result = await run_in_threadpool(
            service.search,
            body.query,
            scope,
            top_k=body.top_k,
            recall_top_n=min(200, max(50, body.top_k * 5)),
            filters=filters,
            config=config,
            rerank=body.rerank,
        )
    except (EmbeddingError, SearchBackendError) as exc:
        raise AppError(503, "SEARCH_BACKEND_UNAVAILABLE", "检索后端暂不可用") from exc
    except ValueError as exc:
        raise AppError(400, "INVALID_SEARCH_REQUEST", str(exc)) from exc

    items = [_safe_hit(hit) for hit in result.hits]
    items = [item for item in items if item is not None]
    fallback = result.fallback or (bool(result.hits) and not items)
    fallback_reason = result.fallback_reason or ("invalid_evidence" if fallback else None)
    data = {
        "items": items,
        "total": len(items),
        "took_ms": round((time.perf_counter() - started) * 1000, 3),
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "applied_filters": body.filters.model_dump(exclude_none=True),
    }
    return success_response(request, data)


def _safe_hit(hit: RankedHit) -> dict[str, Any] | None:
    source = hit.source
    chunk_id = _safe_text(source.get("chunk_id") or hit.document_id, limit=128)
    document_id = _safe_text(source.get("document_id"), limit=128)
    content = _safe_text(source.get("content"), limit=8000, preserve_whitespace=True)
    if not chunk_id or not document_id or not content:
        return None
    merchant_id = _safe_text(source.get("merchant_id"), limit=128) or None
    source_location = _safe_text(source.get("source_location"), limit=1000)
    if not source_location:
        source_location = f"document/{document_id}#chunk={chunk_id}"
    recall_sources = [value for value in hit.recall_sources if value in {"bm25", "vector"}]
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "merchant_id": merchant_id,
        "content": content,
        "source_location": source_location,
        "source_url": _source_url(source, document_id, chunk_id),
        "score": _safe_score(hit.final_score),
        "score_detail": {
            "bm25": _safe_score(hit.bm25_score),
            "vector": _safe_score(hit.vector_score),
            "fusion": _safe_score(hit.fused_score),
            "rerank": _safe_score(hit.rerank_score) if hit.rerank_score is not None else None,
        },
        "match_explanation": {
            "recall_sources": recall_sources,
            "keyword_matched": "bm25" in recall_sources,
            "semantic_matched": "vector" in recall_sources,
            "reranked": hit.rerank_score is not None,
        },
    }


def _source_url(source: Any, document_id: str, chunk_id: str) -> str:
    knowledge_base_id = _safe_text(source.get("knowledge_base_id"), limit=128)
    return (
        f"/admin/knowledge-bases/{quote(knowledge_base_id, safe='')}"
        f"?document={quote(document_id, safe='')}&chunk={quote(chunk_id, safe='')}"
        if knowledge_base_id
        else f"/app/documents/{quote(document_id, safe='')}?chunk={quote(chunk_id, safe='')}"
    )


def _safe_text(value: Any, *, limit: int, preserve_whitespace: bool = False) -> str:
    if not isinstance(value, str | int):
        return ""
    text = str(value)
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    if not preserve_whitespace:
        text = " ".join(text.split())
    return text.strip()[:limit]


def _safe_score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    number = float(value)
    return number if math.isfinite(number) else 0.0
