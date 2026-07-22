"""Adapters from graph ports to the existing hybrid-search application service."""

from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.contracts import RetrievalRequest
from app.agents.types import RetrievedChunk
from app.infrastructure.search.pipeline import HybridSearchService
from app.infrastructure.search.retrieval import BusinessSearchFilters, TrustedSearchScope


class HybridSearchRetrieverAdapter:
    def __init__(self, service: HybridSearchService) -> None:
        self._service = service

    def retrieve(self, request: RetrievalRequest) -> Sequence[RetrievedChunk]:
        constraints = request.constraints
        result = self._service.search(
            request.query.strip(),
            TrustedSearchScope(
                tenant_id=request.scope.tenant_id,
                knowledge_base_ids=request.scope.knowledge_base_ids,
                resource_scopes=request.scope.resource_scopes,
            ),
            top_k=request.top_k,
            filters=BusinessSearchFilters(
                categories=constraints.cuisines,
                price_cent_lte=constraints.budget_cent_per_person_lte,
                distance_meter_lte=constraints.distance_meter_lte,
                open_now=constraints.open_now,
            ),
        )
        if result.fallback:
            return ()
        return tuple(_to_chunk(hit.document_id, hit.final_score, hit.source) for hit in result.hits)


def _to_chunk(document_id: str, score: float, source: Any) -> RetrievedChunk:
    nested_metadata = source.get("metadata")
    metadata = dict(nested_metadata) if isinstance(nested_metadata, Mapping) else {}
    metadata.update(source)
    return RetrievedChunk(
        chunk_id=str(source.get("chunk_id") or document_id),
        content=str(source.get("content") or ""),
        score=score,
        source_location=str(
            source.get("source_location") or source.get("source_key") or document_id
        ),
        merchant_id=_optional_string(source.get("merchant_id")),
        data_updated_at=_optional_string(
            source.get("last_verified_at")
            or source.get("updated_at")
            or metadata.get("last_verified_at")
            or metadata.get("updated_at")
        ),
        metadata=metadata,
    )


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)
