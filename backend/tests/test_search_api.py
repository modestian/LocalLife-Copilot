from unittest.mock import MagicMock
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_current_principal
from app.api.search import get_search_service
from app.application.authorization import (
    AuthorizationPrincipal,
    PermissionRule,
    ResourceGrantRule,
    ResourceType,
)
from app.core.config import Settings
from app.infrastructure.search.ranking import RankedHit, RankingResult
from app.main import create_app

TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b121")
KB_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b123")


def principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125"),
        username="search-user",
        display_name="Search User",
        email=None,
        department_id=TENANT_ID,
        roles=(),
        permissions=(PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),),
        resource_grants=(ResourceGrantRule(ResourceType.KNOWLEDGE_BASE, KB_ID, "READ"),),
    )


def build_client(service: MagicMock) -> TestClient:
    app = create_app(readiness_checks={}, settings=Settings(search_minimum_score=0.1))
    app.dependency_overrides[get_current_principal] = principal
    app.dependency_overrides[get_search_service] = lambda: service
    return TestClient(app)


def payload() -> dict[str, object]:
    return {
        "query": "quiet cafe",
        "knowledge_base_ids": [str(KB_ID)],
        "top_k": 10,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "rerank": True,
        "filters": {"category": ["cafe"], "open_now": True},
    }


def test_search_returns_explainable_allowlisted_evidence_and_server_source_url() -> None:
    service = MagicMock()
    service.search.return_value = RankingResult(
        hits=(
            RankedHit(
                document_id="projection-1",
                source={
                    "chunk_id": "chunk-1",
                    "document_id": "doc-1",
                    "knowledge_base_id": str(KB_ID),
                    "merchant_id": "merchant-1",
                    "content": "Quiet environment suitable for discussion.",
                    "source_location": "reviews/merchant-a/2026-06-10",
                    "source_url": "javascript:alert(1)",
                    "content_vector": [0.1, 0.2],
                    "tenant_id": "must-not-leak",
                },
                fused_score=0.82,
                final_score=0.91,
                recall_sources=("bm25", "vector"),
                bm25_score=4.2,
                vector_score=0.88,
            ),
        ),
        fallback=False,
    )

    with build_client(service) as client:
        response = client.post("/api/v1/search", json=payload())

    assert response.status_code == 200
    data = response.json()["data"]
    hit = data["items"][0]
    assert hit["source_url"].startswith(
        f"/admin/knowledge-bases/{KB_ID}?document=doc-1&chunk=chunk-1"
    )
    assert hit["score_detail"] == {
        "bm25": 4.2,
        "vector": 0.88,
        "fusion": 0.82,
        "rerank": None,
    }
    assert hit["match_explanation"]["recall_sources"] == ["bm25", "vector"]
    assert "content_vector" not in response.text
    assert "must-not-leak" not in response.text
    scope = service.search.call_args.args[1]
    assert scope.tenant_id == str(TENANT_ID)
    assert scope.knowledge_base_ids == frozenset({str(KB_ID)})


def test_search_low_score_fallback_is_explicit_and_empty() -> None:
    service = MagicMock()
    service.search.return_value = RankingResult((), True, "low_score")

    with build_client(service) as client:
        response = client.post("/api/v1/search", json=payload())

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0
    assert data["fallback"] is True
    assert data["fallback_reason"] == "low_score"
    assert data["applied_filters"] == {
        "category": ["cafe"],
        "open_now": True,
        "document_type": [],
    }


def test_search_rejects_unknown_fields_and_invalid_weights() -> None:
    service = MagicMock()
    invalid = payload()
    invalid["tenant_id"] = str(TENANT_ID)
    invalid["vector_weight"] = 0.9

    with build_client(service) as client:
        response = client.post("/api/v1/search", json=invalid)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    service.search.assert_not_called()
