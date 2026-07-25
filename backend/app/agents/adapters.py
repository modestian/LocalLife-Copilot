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

        def _search(with_cuisine=True):
            return self._service.search(
                request.query.strip(),
                TrustedSearchScope(
                    tenant_id=request.scope.tenant_id,
                    knowledge_base_ids=request.scope.knowledge_base_ids,
                    resource_scopes=request.scope.resource_scopes,
                ),
                top_k=request.top_k,
                filters=BusinessSearchFilters(
                    categories=constraints.cuisines if with_cuisine else (),
                    price_cent_lte=constraints.budget_cent_per_person_lte,
                    distance_meter_lte=constraints.distance_meter_lte,
                    open_now=constraints.open_now,
                ),
            )

        # Always skip category filter - OpenSearch terms query on category_ids is broken
        result = _search(with_cuisine=False)
        if result.fallback:
            return ()
        hits = result.hits
        merchant_matches = tuple(
            hit for hit in hits if _matches_merchant_name(request.query, hit.source)
        )
        if merchant_matches:
            hits = merchant_matches
        return tuple(_to_chunk(hit.document_id, hit.final_score, hit.source) for hit in hits)


def _matches_merchant_name(query: str, source: Mapping[str, Any]) -> bool:
    merchant_query = query.partition("[探店条件]")[0].strip()
    if len(merchant_query) < 2:
        return False
    metadata = source.get("metadata")
    nested = metadata if isinstance(metadata, Mapping) else {}
    merchant_name = str(source.get("merchant_name") or nested.get("merchant_name") or "").strip()
    return bool(
        merchant_name and (merchant_query in merchant_name or merchant_name in merchant_query)
    )


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
