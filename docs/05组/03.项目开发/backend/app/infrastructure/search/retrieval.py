"""Permission-safe BM25 and k-NN recall for the Chunk search projection."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opensearchpy import OpenSearch
from opensearchpy.exceptions import OpenSearchException


class SearchBackendError(RuntimeError):
    """Stable failure raised when OpenSearch cannot complete both recall paths."""


@dataclass(frozen=True, slots=True)
class TrustedSearchScope:
    """Server-derived authorization scope; never construct this from request JSON alone."""

    tenant_id: str
    knowledge_base_ids: frozenset[str]
    resource_scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        if any(not value.strip() for value in self.knowledge_base_ids):
            raise ValueError("knowledge_base_ids must not contain blank values")
        if any(not value.strip() for value in self.resource_scopes):
            raise ValueError("resource_scopes must not contain blank values")


@dataclass(frozen=True, slots=True)
class BusinessSearchFilters:
    """Validated, non-security filters accepted by the public search contract."""

    categories: tuple[str, ...] = ()
    price_cent_lte: int | None = None
    distance_meter_lte: int | None = None
    open_now: bool | None = None
    document_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecallHit:
    document_id: str
    score: float
    source: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class DualRecallResult:
    bm25: tuple[RecallHit, ...]
    vector: tuple[RecallHit, ...]


class OpenSearchDualRetriever:
    """Execute keyword and vector recall with identical mandatory security filters."""

    def __init__(self, client: OpenSearch, *, index: str) -> None:
        if not index.strip():
            raise ValueError("search index must not be blank")
        self._client = client
        self._index = index

    def recall(
        self,
        query: str,
        query_vector: Sequence[float],
        scope: TrustedSearchScope,
        *,
        top_n: int = 50,
        now: datetime | None = None,
        filters: BusinessSearchFilters | None = None,
    ) -> DualRecallResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("search query must not be blank")
        if top_n <= 0:
            raise ValueError("top_n must be greater than zero")
        vector = _validated_vector(query_vector)
        mandatory_filter = mandatory_search_filter(scope, now=now)
        effective_filter = combined_search_filter(mandatory_filter, filters)
        body = [
            {},
            _bm25_body(normalized_query, effective_filter, top_n),
            {},
            _knn_body(vector, effective_filter, top_n),
        ]

        try:
            response = self._client.msearch(index=self._index, body=body)
            responses = response["responses"]
            if not isinstance(responses, list) or len(responses) != 2:
                raise TypeError("unexpected msearch response count")
            if any("error" in item for item in responses):
                raise TypeError("one or more recall paths failed")
            return DualRecallResult(
                bm25=_parse_hits(responses[0]),
                vector=_parse_hits(responses[1]),
            )
        except (KeyError, TypeError, ValueError, OSError, OpenSearchException) as exc:
            raise SearchBackendError("hybrid recall failed") from exc


def mandatory_search_filter(
    scope: TrustedSearchScope, *, now: datetime | None = None
) -> dict[str, Any]:
    """Build filters that callers cannot weaken with business request parameters."""
    timestamp = _utc_timestamp(now or datetime.now(UTC))
    filters: list[dict[str, Any]] = [{"term": {"tenant_id": scope.tenant_id}}]
    if not scope.knowledge_base_ids or not scope.resource_scopes:
        filters.append({"match_none": {}})
    else:
        filters.extend(
            [
                {"terms": {"knowledge_base_id": sorted(scope.knowledge_base_ids)}},
                {"terms": {"resource_scope": sorted(scope.resource_scopes)}},
            ]
        )
    filters.extend(
        [
            _missing_or_range("valid_from", lte=timestamp),
            _missing_or_range("valid_to", gt=timestamp),
            {
                "bool": {
                    "should": [
                        _missing_field("business_status"),
                        {"term": {"business_status": "OPEN"}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        ]
    )
    return {"bool": {"filter": filters}}


def combined_search_filter(
    mandatory_filter: Mapping[str, Any], filters: BusinessSearchFilters | None
) -> dict[str, Any]:
    """Append request filters without ever replacing the mandatory security filter."""
    clauses: list[dict[str, Any]] = [dict(mandatory_filter)]
    if filters is None:
        return {"bool": {"filter": clauses}}
    if filters.categories:
        clauses.append({"terms": {"category_ids": list(filters.categories)}})
    if filters.price_cent_lte is not None:
        clauses.append({"range": {"price_cent": {"lte": filters.price_cent_lte}}})
    if filters.distance_meter_lte is not None:
        clauses.append(
            {
                "bool": {
                    "should": [
                        {"bool": {"must_not": [{"exists": {"field": "distance_meter"}}]}},
                        {"range": {"distance_meter": {"lte": filters.distance_meter_lte}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    # The lifecycle filter always excludes closed businesses. A request for
    # explicitly closed businesses therefore fails closed instead of weakening it.
    if filters.open_now is False:
        clauses.append({"match_none": {}})
    if filters.document_types:
        values = sorted(
            {variant for value in filters.document_types for variant in (value, value.upper())}
        )
        clauses.append({"terms": {"source_type": values}})
    return {"bool": {"filter": clauses}}


def _bm25_body(query: str, mandatory_filter: Mapping[str, Any], top_n: int) -> dict[str, Any]:
    return {
        "size": top_n,
        "track_total_hits": False,
        "query": {
            "bool": {
                "must": [{"match": {"content": {"query": query, "_name": "bm25_content"}}}],
                "filter": [mandatory_filter],
            }
        },
    }


def _knn_body(
    vector: Sequence[float], mandatory_filter: Mapping[str, Any], top_n: int
) -> dict[str, Any]:
    return {
        "size": top_n,
        "track_total_hits": False,
        "query": {
            "knn": {
                "content_vector": {
                    "vector": list(vector),
                    "k": top_n,
                    "filter": mandatory_filter,
                }
            }
        },
    }


def _missing_or_range(field: str, **condition: str) -> dict[str, Any]:
    return {
        "bool": {
            "should": [_missing_field(field), {"range": {field: condition}}],
            "minimum_should_match": 1,
        }
    }


def _missing_field(field: str) -> dict[str, Any]:
    return {"bool": {"must_not": [{"exists": {"field": field}}]}}


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("search time must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _validated_vector(vector: Sequence[float]) -> list[float]:
    if not vector:
        raise ValueError("query vector must not be empty")
    result: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("query vector must contain only numbers")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("query vector must contain only finite numbers")
        result.append(number)
    return result


def _parse_hits(response: Mapping[str, Any]) -> tuple[RecallHit, ...]:
    raw_hits = response["hits"]["hits"]
    if not isinstance(raw_hits, list):
        raise TypeError("search hits must be a list")
    hits: list[RecallHit] = []
    for item in raw_hits:
        source = item.get("_source", {})
        if not isinstance(source, Mapping):
            raise TypeError("search hit source must be an object")
        hits.append(
            RecallHit(
                document_id=str(item["_id"]),
                score=float(item.get("_score") or 0.0),
                source=source,
            )
        )
    return tuple(hits)
