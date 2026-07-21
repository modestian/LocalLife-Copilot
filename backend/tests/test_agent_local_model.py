from uuid import uuid4

from app.agents.generation import GroundedRAGGenerator
from app.agents.local_model import ExtractiveModelAdapter
from app.agents.types import RetrievedChunk


def _chunk(content: str = "青禾咖啡馆环境安静，适合两人聊天。") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=str(uuid4()),
        content=content,
        score=0.92,
        source_location="reviews/qinghe/1",
        merchant_id="merchant-qinghe",
        data_updated_at="2026-07-20T08:00:00Z",
        metadata={
            "merchant_name": "青禾咖啡馆",
            "category": "咖啡",
            "avg_price_cent": 5800,
            "business_status": "OPEN",
        },
    )


def test_extractive_model_produces_verified_recommendation() -> None:
    result = GroundedRAGGenerator(ExtractiveModelAdapter()).generate(
        {
            "conversation_id": "c-1",
            "user_query": "推荐安静的咖啡店",
            "retrieved_chunks": (_chunk(),),
        }
    )

    assert not result.is_fallback
    assert "青禾咖啡馆" in result.answer
    assert "数据更新：2026-07-20T08:00:00Z" in result.answer
    assert result.sources[0].source_location == "reviews/qinghe/1"


def test_extractive_model_produces_verified_review_summary() -> None:
    result = GroundedRAGGenerator(ExtractiveModelAdapter()).generate(
        {
            "conversation_id": "c-1",
            "user_query": "总结青禾咖啡馆的评价",
            "retrieved_chunks": (_chunk(),),
        }
    )

    assert not result.is_fallback
    assert "评价摘要" in result.answer
    assert "环境安静" in result.answer
    assert len(result.sources) == 1


def test_extractive_model_produces_verified_grounded_answer() -> None:
    result = GroundedRAGGenerator(ExtractiveModelAdapter()).generate(
        {
            "conversation_id": "c-1",
            "user_query": "青禾咖啡馆有什么特点",
            "retrieved_chunks": (_chunk(),),
        }
    )

    assert not result.is_fallback
    assert result.answer.endswith("[E1]")
    assert result.sources[0].content_snapshot.startswith("青禾咖啡馆")