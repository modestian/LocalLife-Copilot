from collections.abc import Sequence
from uuid import uuid4

import pytest

from app.agents.contracts import ModelInput, ModelPrediction
from app.agents.generation import (
    NO_EVIDENCE_ANSWER,
    CitationPolicy,
    GroundedGeneration,
    GroundedRAGGenerator,
)
from app.agents.persistence import GroundedPersistenceError, GroundedResponsePersister
from app.agents.types import RetrievedChunk, SourceCitation


class StaticModel:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        self.calls += len(batch)
        return [ModelPrediction(text="", structured=self.payload, model_version="model-v1")]


def chunk(*, score: float = 0.9, content: str = "quiet atmosphere, rating 4.6") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        content=content,
        score=score,
        source_location="reviews/merchant-a/2026-07-20#atmosphere",
        merchant_id="merchant-1",
        data_updated_at="2026-07-20T08:00:00Z",
        metadata={
            "merchant_name": "Quiet Bistro",
            "category": "Sichuan",
            "rating": 4.6,
        },
    )


def recommendation(*, rating: float = 4.6) -> dict[str, object]:
    return {
        "response_type": "recommendation",
        "answer": "",
        "recommendations": [
            {
                "merchant_id": "merchant-1",
                "name": "Quiet Bistro",
                "category": "Sichuan",
                "reason": "quiet atmosphere",
                "rating": rating,
                "data_updated_at": "2026-07-20T08:00:00Z",
                "source_ids": ["E1"],
            }
        ],
        "review_summary": None,
        "source_ids": [],
    }


def test_low_score_and_insufficient_evidence_fall_back_before_model_call() -> None:
    model = StaticModel(recommendation())
    generator = GroundedRAGGenerator(
        model,
        citation_policy=CitationPolicy(min_evidence_score=0.8, min_evidence_count=2),
    )

    result = generator.generate(
        {
            "conversation_id": "conversation-1",
            "user_query": "\u63a8\u8350\u9910\u5385",
            "retrieved_chunks": (chunk(score=0.9), chunk(score=0.7)),
        }
    )

    assert result.fallback_reason == "insufficient_evidence"
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.sources == ()
    assert model.calls == 0


def test_cited_but_unsupported_structured_fact_is_rejected() -> None:
    result = GroundedRAGGenerator(StaticModel(recommendation(rating=5.0))).generate(
        {
            "conversation_id": "conversation-1",
            "user_query": "\u63a8\u8350\u9910\u5385",
            "retrieved_chunks": (chunk(),),
        }
    )

    assert result.fallback_reason == "unsupported_citations"
    assert result.sources == ()


@pytest.mark.parametrize(
    "answer",
    [
        "quiet atmosphere.",
        "Michelin three stars [E1].",
    ],
)
def test_uncited_or_unsupported_grounded_claim_is_rejected(answer: str) -> None:
    payload = {
        "response_type": "grounded_answer",
        "answer": answer,
        "recommendations": [],
        "review_summary": None,
        "source_ids": ["E1"],
    }
    result = GroundedRAGGenerator(StaticModel(payload)).generate(
        {
            "conversation_id": "conversation-1",
            "user_query": "what does the evidence say",
            "retrieved_chunks": (chunk(),),
        }
    )

    assert result.fallback_reason == "unsupported_citations"


def test_verified_citation_keeps_locator_and_exact_prompt_snapshot() -> None:
    payload = {
        "response_type": "grounded_answer",
        "answer": "quiet atmosphere [E1].",
        "recommendations": [],
        "review_summary": None,
        "source_ids": ["E1"],
    }
    result = GroundedRAGGenerator(
        StaticModel(payload), max_chunk_chars=16, max_total_evidence_chars=16
    ).generate(
        {
            "conversation_id": "conversation-1",
            "user_query": "what does the evidence say",
            "retrieved_chunks": (chunk(content="quiet atmosphere and hidden tail"),),
        }
    )

    assert result.is_fallback is False
    assert result.sources[0].evidence_id == "E1"
    assert result.sources[0].source_location.endswith("#atmosphere")
    assert result.sources[0].content_snapshot == "quiet atmosphere"


class CapturingRepository:
    def __init__(self) -> None:
        self.payload = None

    async def append_message(self, _conversation_id, _owner_user_id, payload):
        self.payload = payload
        return payload


@pytest.mark.asyncio
async def test_verified_sources_are_mapped_to_atomic_message_persistence() -> None:
    repository = CapturingRepository()
    persister = GroundedResponsePersister(repository)  # type: ignore[arg-type]
    chunk_id = uuid4()
    generation = GroundedGeneration(
        answer="quiet atmosphere [E1].",
        structured=None,
        sources=(
            SourceCitation(
                chunk_id=str(chunk_id),
                rank_no=1,
                source_location="reviews/merchant-a#atmosphere",
                content_snapshot="quiet atmosphere",
                score=0.91,
                evidence_id="E1",
            ),
        ),
        model_version="model-v1",
    )

    result = await persister.persist(uuid4(), uuid4(), generation, request_id="request-1")

    assert result is repository.payload
    assert repository.payload.role.value == "ASSISTANT"
    assert repository.payload.sources[0].chunk_id == chunk_id
    assert repository.payload.sources[0].content_snapshot == "quiet atmosphere"


@pytest.mark.asyncio
async def test_non_uuid_source_is_rejected_before_repository_write() -> None:
    repository = CapturingRepository()
    persister = GroundedResponsePersister(repository)  # type: ignore[arg-type]
    generation = GroundedGeneration(
        answer="answer",
        structured=None,
        sources=(SourceCitation("not-a-uuid", 1, "location", "snapshot"),),
        model_version=None,
    )

    with pytest.raises(GroundedPersistenceError):
        await persister.persist(uuid4(), uuid4(), generation)
    assert repository.payload is None
