from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.infrastructure.search.retrieval import (
    BusinessSearchFilters,
    OpenSearchDualRetriever,
    SearchBackendError,
    TrustedSearchScope,
    mandatory_search_filter,
)

NOW = datetime(2026, 7, 18, 8, 30, tzinfo=UTC)


def trusted_scope() -> TrustedSearchScope:
    return TrustedSearchScope(
        tenant_id="tenant-1",
        knowledge_base_ids=frozenset({"kb-2", "kb-1"}),
        resource_scopes=frozenset({"PUBLIC", "DEPARTMENT:42"}),
    )


def test_mandatory_filter_contains_all_security_and_lifecycle_constraints() -> None:
    query_filter = mandatory_search_filter(trusted_scope(), now=NOW)
    filters = query_filter["bool"]["filter"]

    assert {"term": {"tenant_id": "tenant-1"}} in filters
    assert {"terms": {"knowledge_base_id": ["kb-1", "kb-2"]}} in filters
    assert {"terms": {"resource_scope": ["DEPARTMENT:42", "PUBLIC"]}} in filters
    assert {
        "bool": {
            "should": [
                {"bool": {"must_not": [{"exists": {"field": "valid_from"}}]}},
                {"range": {"valid_from": {"lte": "2026-07-18T08:30:00Z"}}},
            ],
            "minimum_should_match": 1,
        }
    } in filters
    assert {
        "bool": {
            "should": [
                {"bool": {"must_not": [{"exists": {"field": "valid_to"}}]}},
                {"range": {"valid_to": {"gt": "2026-07-18T08:30:00Z"}}},
            ],
            "minimum_should_match": 1,
        }
    } in filters
    assert filters[-1]["bool"]["should"][-1] == {"term": {"business_status": "OPEN"}}


@pytest.mark.parametrize(
    ("knowledge_base_ids", "resource_scopes"),
    [(frozenset(), frozenset({"PUBLIC"})), (frozenset({"kb-1"}), frozenset())],
)
def test_empty_authorization_scope_fails_closed(knowledge_base_ids, resource_scopes) -> None:
    scope = TrustedSearchScope("tenant-1", knowledge_base_ids, resource_scopes)

    query_filter = mandatory_search_filter(scope, now=NOW)

    assert {"match_none": {}} in query_filter["bool"]["filter"]


def test_dual_retriever_submits_bm25_and_knn_with_the_same_mandatory_filter() -> None:
    client = MagicMock()
    client.msearch.return_value = {
        "responses": [
            {
                "hits": {
                    "hits": [{"_id": "version:0", "_score": 4.2, "_source": {"content": "安静"}}]
                }
            },
            {
                "hits": {
                    "hits": [{"_id": "version:1", "_score": 0.91, "_source": {"content": "咖啡"}}]
                }
            },
        ]
    }

    result = OpenSearchDualRetriever(client, index="chunks-read").recall(
        " 安静的咖啡馆 ", [0.1, 0.2, 0.3], trusted_scope(), top_n=20, now=NOW
    )

    call = client.msearch.call_args.kwargs
    assert call["index"] == "chunks-read"
    body = call["body"]
    assert len(body) == 4
    bm25 = body[1]
    vector = body[3]
    assert bm25["size"] == vector["size"] == 20
    assert bm25["query"]["bool"]["must"][0]["match"]["content"]["query"] == "安静的咖啡馆"
    bm25_filter = bm25["query"]["bool"]["filter"][0]
    vector_query = vector["query"]["knn"]["content_vector"]
    assert vector_query["vector"] == [0.1, 0.2, 0.3]
    assert vector_query["k"] == 20
    assert vector_query["filter"] == bm25_filter
    assert result.bm25[0].document_id == "version:0"
    assert result.bm25[0].score == 4.2
    assert result.vector[0].source["content"] == "咖啡"


def test_business_filters_are_identical_on_both_recall_paths_and_cannot_replace_scope() -> None:
    client = MagicMock()
    client.msearch.return_value = {"responses": [{"hits": {"hits": []}}, {"hits": {"hits": []}}]}

    OpenSearchDualRetriever(client, index="chunks-read").recall(
        "coffee",
        [0.1],
        trusted_scope(),
        filters=BusinessSearchFilters(
            categories=("cafe",),
            price_cent_lte=6000,
            distance_meter_lte=3000,
            open_now=True,
            document_types=("review",),
        ),
        now=NOW,
    )

    body = client.msearch.call_args.kwargs["body"]
    bm25_filter = body[1]["query"]["bool"]["filter"][0]
    vector_filter = body[3]["query"]["knn"]["content_vector"]["filter"]
    assert bm25_filter == vector_filter
    clauses = bm25_filter["bool"]["filter"]
    assert clauses[0] == mandatory_search_filter(trusted_scope(), now=NOW)
    assert {"terms": {"category_ids": ["cafe"]}} in clauses
    assert {"range": {"price_cent": {"lte": 6000}}} in clauses
    # Distance filter now allows missing fields
    distance_clause = {
        "bool": {
            "should": [
                {"bool": {"must_not": [{"exists": {"field": "distance_meter"}}]}},
                {"range": {"distance_meter": {"lte": 3000}}},
            ],
            "minimum_should_match": 1,
        }
    }
    assert distance_clause in clauses
    assert {"terms": {"source_type": ["REVIEW", "review"]}} in clauses


def test_dual_retriever_does_not_return_partial_results_when_one_path_fails() -> None:
    client = MagicMock()
    client.msearch.return_value = {
        "responses": [
            {"hits": {"hits": []}},
            {"error": {"type": "query_shard_exception", "reason": "bad vector"}},
        ]
    }

    with pytest.raises(SearchBackendError, match="hybrid recall failed"):
        OpenSearchDualRetriever(client, index="chunks-read").recall(
            "咖啡馆", [0.1], trusted_scope(), now=NOW
        )


@pytest.mark.parametrize("vector", [[], [float("nan")], [True], ["bad"]])
def test_dual_retriever_rejects_invalid_vectors(vector) -> None:
    with pytest.raises(ValueError):
        OpenSearchDualRetriever(MagicMock(), index="chunks-read").recall(
            "咖啡馆", vector, trusted_scope(), now=NOW
        )


def test_mandatory_filter_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        mandatory_search_filter(trusted_scope(), now=datetime(2026, 7, 18))
