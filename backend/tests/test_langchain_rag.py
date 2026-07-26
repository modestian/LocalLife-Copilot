"""Unit tests for langchain_rag.py helpers — no LangChain / Bailian dependency."""

from app.agents.langchain_rag import (
    NO_EVIDENCE_ANSWER,
    RAGGeneration,
    SimpleRAGGenerator,
    _bounded_history,
    _safe_float,
    _safe_int,
    chunks_to_citations,
    chunks_to_context,
    chunks_to_documents,
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
        self._general_chain = None


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


class _RecordingChain:
    def __init__(self, response: str) -> None:
        self.response = response
        self.payloads: list[dict[str, str]] = []

    def invoke(self, payload: dict[str, str]) -> str:
        self.payloads.append(payload)
        return self.response


def test_simple_rag_passes_bounded_history_to_model() -> None:
    gen = _FakeGenerator(has_api_key=True)
    gen._model.version = "test-model"
    chain = _RecordingChain("结合上文回答")
    gen._chain = chain

    result = gen.generate("第二家呢？", (_chunk(),), "USER: 推荐海鲜\nASSISTANT: 第二家是鲜入围")

    assert result.answer == "结合上文回答"
    assert chain.payloads[0]["history"].endswith("ASSISTANT: 第二家是鲜入围")


def test_general_chat_uses_history_and_falls_back_without_model() -> None:
    gen = _FakeGenerator(has_api_key=True)
    gen._model.version = "test-model"
    chain = _RecordingChain("记得，你叫小林。")
    gen._general_chain = chain

    result = gen.generate_general("我叫什么？", "USER: 我叫小林")

    assert result.answer == "记得，你叫小林。"
    assert chain.payloads == [{"query": "我叫什么？", "history": "USER: 我叫小林"}]


# ---------------------------------------------------------------------------
# chunks_to_documents
# ---------------------------------------------------------------------------


def test_chunks_to_documents_empty() -> None:
    assert chunks_to_documents(()) == []


def test_chunks_to_documents_includes_metadata() -> None:
    c = _chunk(content="测试", merchant_id="m99", score=0.95)
    docs = chunks_to_documents((c,))
    assert len(docs) == 1
    assert docs[0].page_content == "测试"
    assert docs[0].metadata["merchant_name"] == "测试商家"
    assert docs[0].metadata["avg_price_cent"] == 8000
    assert docs[0].metadata["source_location"] == "reviews/test/1"
    assert docs[0].metadata["score"] == 0.95
    assert docs[0].metadata["merchant_id"] == "m99"


def test_chunks_to_documents_skips_missing_merchant_id() -> None:
    c = RetrievedChunk(
        chunk_id="minimal",
        content="仅内容",
        score=0.5,
        source_location="x",
        metadata={},
    )
    docs = chunks_to_documents((c,))
    assert "merchant_name" not in docs[0].metadata
    assert "merchant_id" not in docs[0].metadata


# ---------------------------------------------------------------------------
# _safe_int / _safe_float
# ---------------------------------------------------------------------------


def test_safe_int_valid() -> None:
    assert _safe_int(42) == 42
    assert _safe_int("100") == 100
    assert _safe_int(None) is None


def test_safe_int_invalid() -> None:
    assert _safe_int("abc") is None
    assert _safe_int([1, 2, 3]) is None


def test_safe_float_invalid() -> None:
    assert _safe_float("not-a-number") is None
    assert _safe_float(object()) is None
    assert _safe_float(None) is None


# ---------------------------------------------------------------------------
# _bounded_history
# ---------------------------------------------------------------------------


def test_bounded_history_empty_returns_placeholder() -> None:
    assert _bounded_history("") == "（无历史对话）"
    assert _bounded_history("   ") == "（无历史对话）"


def test_bounded_history_preserves_short_content() -> None:
    result = _bounded_history("USER: 推荐海鲜\nASSISTANT: 为您推荐海味坊")
    assert "海味坊" in result


# ---------------------------------------------------------------------------
# chunks_to_context — price unit edge cases
# ---------------------------------------------------------------------------


def test_chunks_to_context_price_cent_to_yuan() -> None:
    c = _chunk(content="实惠", merchant_name="平价店", price_cent=1500)
    result = chunks_to_context((c,))
    assert "人均(元): 15" in result


def test_chunks_to_context_price_cent_zero() -> None:
    # 0 is falsy — "0 or fallback" short-circuits, so 0 is silently skipped
    c = _chunk(content="免费", merchant_name="零元店", price_cent=0)
    result = chunks_to_context((c,))
    assert "人均(元)" not in result


def test_chunks_to_context_price_cent_non_numeric_skipped() -> None:
    c = RetrievedChunk(
        chunk_id="c2",
        content="描述",
        score=0.8,
        source_location="x",
        merchant_id="m2",
        metadata={
            "merchant_name": "测试",
            "avg_price_cent": "N/A",
            "category": "其他",
            "rating": 4.0,
        },
    )
    result = chunks_to_context((c,))
    assert "人均(元)" not in result


def test_chunks_to_context_uses_price_cent_fallback() -> None:
    c = RetrievedChunk(
        chunk_id="c1",
        content="内容",
        score=0.8,
        source_location="x",
        merchant_id="m1",
        metadata={"merchant_name": "测试", "price_cent": 2500, "category": "其他", "rating": 4.0},
    )
    result = chunks_to_context((c,))
    assert "人均(元): 25" in result


def test_chunks_to_context_skips_empty_string_values() -> None:
    c = RetrievedChunk(
        chunk_id="c1",
        content="内容",
        score=0.8,
        source_location="x",
        merchant_id="m1",
        metadata={
            "merchant_name": "测试",
            "category": "",
            "rating": "",
            "distance_meter": "",
            "avg_price_cent": 5000,
        },
    )
    result = chunks_to_context((c,))
    assert "分类:" not in result
    assert "评分:" not in result
    assert "距离(米):" not in result


# ---------------------------------------------------------------------------
# stream_generate — no-chunks / no-api-key paths (no LangChain needed)
# ---------------------------------------------------------------------------


def _stream_collect(gen, query: str, chunks, history: str = ""):
    results: list[tuple[str, RAGGeneration | None]] = []
    for token, result in gen.stream_generate(query, chunks, history):
        results.append((token, result))
    return results


def test_stream_generate_no_chunks() -> None:
    gen = _FakeGenerator()
    results = _stream_collect(gen, "查询", ())
    assert len(results) == 1
    _, final = results[0]
    assert final is not None
    assert final.answer == NO_EVIDENCE_ANSWER
    assert final.fallback_reason == "no_evidence"


def test_stream_generate_no_api_key() -> None:
    gen = _FakeGenerator(has_api_key=False)
    c = _chunk(content="好吃")
    results = _stream_collect(gen, "查询", (c,))
    assert len(results) == 1
    _, final = results[0]
    assert final is not None
    assert final.fallback_reason == "no_api_key"
    assert len(final.sources) == 1


def test_stream_generate_general_no_api_key() -> None:
    gen = _FakeGenerator(has_api_key=False)
    results: list[tuple[str, RAGGeneration | None]] = []
    for token, result in gen.stream_generate_general("你好"):
        results.append((token, result))
    assert len(results) == 1
    _, final = results[0]
    assert final is not None
    assert final.fallback_reason == "no_api_key"
    assert final.sources == ()
