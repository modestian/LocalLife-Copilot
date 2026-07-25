"""Unit tests for langchain_rag.py helpers — no LangChain / Bailian dependency."""

from app.agents.langchain_rag import (
    NO_EVIDENCE_ANSWER,
    RAGGeneration,
    SimpleRAGGenerator,
    chunks_to_citations,
    chunks_to_context,
    render_fallback,
)
from app.agents.types import RetrievedChunk


def _chunk(
    content: str = "测试内容",
    *,
    chunk_id: str = "c1",
    merchant_id: str = "m1",
    merchant_name: str = "测试商家",
    category: str = "海鲜",
    rating: float = 4.5,
    price_cent: int = 8000,
    distance_meter: int = 500,
    score: float = 0.9,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        content=content,
        score=score,
        source_location="reviews/test/1",
        merchant_id=merchant_id,
        data_updated_at="2026-07-21T08:00:00Z",
        metadata={
            "merchant_name": merchant_name,
            "category": category,
            "rating": rating,
            "avg_price_cent": price_cent,
            "distance_meter": distance_meter,
            "business_status": "OPEN",
        },
    )


# ---------------------------------------------------------------------------
# chunks_to_citations
# ---------------------------------------------------------------------------


def test_chunks_to_citations_empty() -> None:
    assert chunks_to_citations(()) == ()


def test_chunks_to_citations_builds_evidence_ids() -> None:
    c1 = _chunk(content="A", chunk_id="id-a")
    c2 = _chunk(content="B", chunk_id="id-b")
    citations = chunks_to_citations((c1, c2))
    assert len(citations) == 2
    assert citations[0].evidence_id == "E1"
    assert citations[0].chunk_id == "id-a"
    assert citations[1].evidence_id == "E2"
    assert citations[1].chunk_id == "id-b"


def test_chunks_to_citations_preserves_snapshot() -> None:
    c = _chunk(content="A" * 300)
    citations = chunks_to_citations((c,))
    assert len(citations[0].content_snapshot) == 200  # truncated to 200


# ---------------------------------------------------------------------------
# chunks_to_context
# ---------------------------------------------------------------------------


def test_chunks_to_context_empty() -> None:
    result = chunks_to_context(())
    assert "未找到相关商家资料" in result


def test_chunks_to_context_formats_fields() -> None:
    c = _chunk(content="很好吃", merchant_name="海味坊", rating=4.3, price_cent=5000)
    result = chunks_to_context((c,))
    assert "海味坊" in result
    assert "4.3" in result
    assert "很好吃" in result


def test_chunks_to_context_multiple() -> None:
    c1 = _chunk(content="A", merchant_name="X")
    c2 = _chunk(content="B", merchant_name="Y")
    result = chunks_to_context((c1, c2))
    assert "[商家 1]" in result
    assert "[商家 2]" in result
    assert "\n\n" in result


# ---------------------------------------------------------------------------
# render_fallback
# ---------------------------------------------------------------------------


def test_render_fallback_empty() -> None:
    assert render_fallback(()) == NO_EVIDENCE_ANSWER


def test_render_fallback_shows_merchant_cards() -> None:
    c = _chunk(merchant_name="蚝门夜宵", category="海鲜", rating=4.3, price_cent=7000)
    result = render_fallback((c,))
    assert "蚝门夜宵" in result
    assert "海鲜" in result
    assert "评分 4.3" in result
    assert "人均约 70 元" in result


def test_render_fallback_deduplicates_by_merchant_id() -> None:
    c1 = _chunk(merchant_name="A", merchant_id="m1")
    c2 = _chunk(merchant_name="A", merchant_id="m1")  # same id
    result = render_fallback((c1, c2))
    assert result.count("**A**") == 1  # only once


def test_render_fallback_no_merchant_name_returns_no_evidence() -> None:
    c = _chunk(merchant_name="", merchant_id="")
    result = render_fallback((c,))
    assert result == NO_EVIDENCE_ANSWER


def test_render_fallback_optional_fields() -> None:
    c = _chunk(merchant_name="X", rating=None, price_cent=None, distance_meter=None)
    result = render_fallback((c,))
    assert "评分" not in result
    assert "人均" not in result
    assert "距离" not in result


# ---------------------------------------------------------------------------
# SimpleRAGGenerator (test double, no LangChain)
# ---------------------------------------------------------------------------


class _FakeGenerator(SimpleRAGGenerator):
    def __init__(self, *, has_api_key: bool = False) -> None:
        # Skip parent __init__ which requires LangChainRAGAdapter
        self._model = type("_M", (), {"_api_key": "fake" if has_api_key else ""})()
        self._chain = None


def test_simple_rag_no_chunks_returns_no_evidence() -> None:
    gen = _FakeGenerator()
    result = gen.generate("query", ())
    assert result.answer == NO_EVIDENCE_ANSWER
    assert result.sources == ()
    assert result.fallback_reason == "no_evidence"


def test_simple_rag_no_api_key_returns_fallback() -> None:
    gen = _FakeGenerator(has_api_key=False)
    c = _chunk(content="很好吃")
    result = gen.generate("query", (c,))
    assert "很好吃" not in result.answer
    assert result.fallback_reason == "no_api_key"
    assert len(result.sources) == 1


def test_rag_generation_dataclass() -> None:
    gen = RAGGeneration(answer="hello", sources=(), fallback_reason="no_evidence")
    assert gen.answer == "hello"
    assert gen.fallback_reason == "no_evidence"
    assert gen.model_version is None
