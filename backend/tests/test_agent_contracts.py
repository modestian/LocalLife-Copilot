from collections.abc import Sequence
from unittest.mock import MagicMock

import pytest

from app.agents import (
    ChatConstraints,
    ChatIntent,
    HybridSearchRetrieverAdapter,
    ModelAdapter,
    ModelInput,
    ModelPrediction,
    RetrievalRequest,
    RetrievalScope,
    RetrievedChunk,
    RetrieverAdapter,
    StateField,
    validate_state_update,
)
from app.agents.contracts import NodeContract
from app.infrastructure.search.ranking import RankedHit, RankingResult
from app.infrastructure.search.retrieval import BusinessSearchFilters, TrustedSearchScope


class StubModel:
    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        return [
            ModelPrediction(text=item.prompt.upper(), model_version="stub-v1") for item in batch
        ]


class StubRetriever:
    def retrieve(self, request: RetrievalRequest) -> Sequence[RetrievedChunk]:
        return ()


def test_adapters_are_structural_and_model_predict_is_batched() -> None:
    model = StubModel()

    assert isinstance(model, ModelAdapter)
    assert isinstance(StubRetriever(), RetrieverAdapter)
    assert model.predict([ModelInput(task="chat", prompt="hello")])[0].text == "HELLO"


def test_state_update_allows_only_documented_fields_and_no_reasoning() -> None:
    validate_state_update({"intent": ChatIntent.KNOWLEDGE_QUERY, "answer": "ok"})

    with pytest.raises(ValueError, match="reasoning"):
        validate_state_update({"chain_of_thought": "private reasoning"})
    with pytest.raises(ValueError, match="unknown"):
        validate_state_update({"debug_payload": {}})
    with pytest.raises(TypeError, match="dict"):
        validate_state_update(None)


def test_node_contract_rejects_ambiguous_read_write_declaration() -> None:
    with pytest.raises(ValueError, match="both required and produced"):
        NodeContract(
            name="bad_node",
            requires=frozenset({StateField.INTENT}),
            produces=frozenset({StateField.INTENT}),
        )


def test_hybrid_search_adapter_maps_constraints_scope_and_ranked_hits() -> None:
    service = MagicMock()
    service.search.return_value = RankingResult(
        hits=(
            RankedHit(
                document_id="doc-1",
                source={
                    "chunk_id": "chunk-1",
                    "content": "安静，适合聊天。",
                    "source_location": "reviews/1#2",
                    "merchant_id": "merchant-1",
                    "updated_at": "2026-07-20T00:00:00Z",
                },
                fused_score=0.5,
                final_score=0.8,
                recall_sources=("bm25", "vector"),
            ),
        ),
        fallback=False,
    )
    adapter = HybridSearchRetrieverAdapter(service)
    scope = RetrievalScope(
        tenant_id="tenant-1",
        knowledge_base_ids=frozenset({"kb-1"}),
        resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
    )

    result = adapter.retrieve(
        RetrievalRequest(
            query="  安静的川菜  ",
            scope=scope,
            constraints=ChatConstraints(
                distance_meter_lte=3000,
                budget_cent_per_person_lte=10000,
                cuisines=("川菜",),
                open_now=True,
            ),
            top_k=3,
        )
    )

    assert result[0].chunk_id == "chunk-1"
    assert result[0].source_location == "reviews/1#2"
    service.search.assert_called_once_with(
        "安静的川菜",
        TrustedSearchScope(
            tenant_id="tenant-1",
            knowledge_base_ids=frozenset({"kb-1"}),
            resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
        ),
        top_k=3,
        filters=BusinessSearchFilters(
            categories=("川菜",),
            price_cent_lte=10000,
            distance_meter_lte=3000,
            open_now=True,
        ),
    )


def test_hybrid_search_adapter_turns_search_fallback_into_no_evidence() -> None:
    service = MagicMock()
    service.search.return_value = RankingResult((), True, "insufficient_evidence")
    adapter = HybridSearchRetrieverAdapter(service)
    request = RetrievalRequest(
        query="不存在的店",
        scope=RetrievalScope(
            tenant_id="tenant-1",
            knowledge_base_ids=frozenset({"kb-1"}),
            resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
        ),
    )

    assert adapter.retrieve(request) == ()
