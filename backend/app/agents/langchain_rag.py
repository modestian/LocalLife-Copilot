"""LangChain-based RAG pipeline — replaces the fragile custom generation stack.

Uses ChatOpenAI (Bailian/DashScope) under the hood, with a clean fallback
that returns raw search results when the LLM is unavailable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

try:
    from langchain_openai import ChatOpenAI
except ImportError:  # pragma: no cover — only needed outside Docker
    ChatOpenAI = None  # type: ignore[assignment]

from app.agents.contracts import ModelAdapter, ModelInput, ModelPrediction
from app.agents.types import RetrievedChunk, SourceCitation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LangChain adapter — a drop-in ModelAdapter backed by ChatOpenAI
# ---------------------------------------------------------------------------


class LangChainRAGAdapter(ModelAdapter):
    """ModelAdapter that uses LangChain + ChatOpenAI (Bailian) for RAG generation.

    Unlike the old TransformersModelAdapter, this does NOT depend on BERT or
    any local model-gateway for classification.  Intent routing stays rule-based.
    """

    version = "langchain-rag-v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("BAILIAN_API_KEY", "")
        self._api_base = api_base or os.getenv(
            "BAILIAN_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self._model_name = model or os.getenv("BAILIAN_MODEL", "qwen-plus")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        if not self._api_key:
            logger.warning("BAILIAN_API_KEY not set — LLM generation will be unavailable")

    # ------------------------------------------------------------------
    # ModelAdapter protocol
    # ------------------------------------------------------------------

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        return tuple(self._predict_one(item) for item in batch)

    def _predict_one(self, item: ModelInput) -> ModelPrediction:
        try:
            chain = _build_chain(
                self._api_key,
                self._api_base,
                self._model_name,
                self._temperature,
                self._max_tokens,
                self._timeout,
            )
            if chain is None:
                raise RuntimeError("langchain-openai not available")
            text = chain.invoke({"query": item.prompt})
            return ModelPrediction(text=text, model_version=self.version)
        except Exception as exc:
            logger.warning("LangChain RAG prediction failed: %s", exc)
            return ModelPrediction(text="", model_version=self.version)


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是本地生活探店助手。根据提供的商家资料回答用户问题。

## 规则（严格遵守）
1. 只基于下方「商家资料」中的信息回答，绝不编造
2. 如果资料中没有符合条件的商家，诚实说"当前资料中没找到完全匹配的商家"，并建议放宽条件
3. 推荐商家时，列出名称、评分、人均、距离等关键信息
4. 用户指定了预算或距离条件时，优先推荐符合条件的
5. 用自然、友好的语气回答"""

_USER_PROMPT = """用户问题：{query}

---
{context}
---

请根据以上资料回答用户问题。"""

_FALLBACK_PROMPT = """用户问题：{query}

（LLM 暂不可用，以下是搜索到的原始商家资料，请直接列出。）"""


def _build_chain(
    api_key: str, api_base: str, model: str, temperature: float, max_tokens: int, timeout: float
):
    """Build the LangChain RAG chain.  Returns None if langchain-openai is unavailable."""
    if ChatOpenAI is None:
        return None
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=1,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            ("user", _USER_PROMPT),
        ]
    )
    return prompt | llm | StrOutputParser()


# ---------------------------------------------------------------------------
# Chunk formatting
# ---------------------------------------------------------------------------

_METADATA_KEYS = (
    "merchant_name",
    "name",
    "category",
    "category_name",
    "rating",
    "avg_price_cent",
    "price_cent",
    "distance_meter",
    "business_status",
)


def chunks_to_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Convert retrieved chunks into a readable text block for the LLM prompt."""
    if not chunks:
        return "（未找到相关商家资料）"
    blocks: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        blocks.append(_format_one(chunk, i))
    return "\n\n".join(blocks)


def chunks_to_citations(chunks: Sequence[RetrievedChunk]) -> tuple[SourceCitation, ...]:
    """Build evidence citations from retrieved chunks."""
    return tuple(
        SourceCitation(
            chunk_id=chunk.chunk_id,
            rank_no=i + 1,
            source_location=chunk.source_location,
            content_snapshot=chunk.content[:200],
            score=chunk.score,
            evidence_id=f"E{i + 1}",
        )
        for i, chunk in enumerate(chunks)
    )


def chunks_to_documents(chunks: Sequence[RetrievedChunk]) -> list[Document]:
    """Convert RetrievedChunk → LangChain Document (for retriever chains)."""
    docs: list[Document] = []
    for chunk in chunks:
        metadata: dict[str, Any] = {}
        for key in _METADATA_KEYS:
            if key in chunk.metadata:
                metadata[key] = chunk.metadata[key]
        metadata["source_location"] = chunk.source_location
        metadata["score"] = chunk.score
        if chunk.merchant_id:
            metadata["merchant_id"] = chunk.merchant_id
        docs.append(Document(page_content=chunk.content, metadata=metadata))
    return docs


# ---------------------------------------------------------------------------
# Local fallback when LLM is unavailable
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _MerchantCard:
    name: str
    category: str = ""
    rating: float | None = None
    price_cent: int | None = None
    distance_meter: int | None = None


def render_fallback(chunks: Sequence[RetrievedChunk]) -> str:
    """Render a best-effort response from search results when the LLM is down."""
    if not chunks:
        return NO_EVIDENCE_ANSWER

    seen: dict[str, _MerchantCard] = {}
    for c in chunks:
        mid = c.merchant_id or c.metadata.get("merchant_id", "")
        name = str(c.metadata.get("merchant_name") or c.metadata.get("name") or "").strip()
        if not mid or not name or mid in seen:
            continue
        seen[mid] = _MerchantCard(
            name=name,
            category=str(c.metadata.get("category", c.metadata.get("category_name", ""))),
            rating=_safe_float(c.metadata.get("rating")),
            price_cent=_safe_int(c.metadata.get("avg_price_cent", c.metadata.get("price_cent"))),
            distance_meter=_safe_int(c.metadata.get("distance_meter")),
        )

    if not seen:
        return NO_EVIDENCE_ANSWER

    lines: list[str] = []
    for card in seen.values():
        extras: list[str] = []
        if card.rating is not None:
            extras.append(f"评分 {card.rating:.1f}")
        if card.price_cent is not None:
            extras.append(f"人均约 {card.price_cent / 100:.0f} 元")
        if card.distance_meter is not None:
            extras.append(f"距离 {card.distance_meter} 米")
        line = f"- **{card.name}**（{card.category}）"
        if extras:
            line += "  " + "  ".join(extras)
        lines.append(line)

    lines.append("")
    lines.append("> 基于已收录资料匹配，AI 模型暂不可用。")
    return "\n".join(lines)


def _safe_float(value: object) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_one(chunk: RetrievedChunk, index: int) -> str:
    meta = chunk.metadata
    parts: list[str] = [f"[商家 {index}]"]
    for label, key in (
        ("名称", "merchant_name"),
        ("分类", "category"),
        ("评分", "rating"),
        ("距离(米)", "distance_meter"),
    ):
        val = meta.get(key)
        if val is not None and val != "":
            parts.append(f"{label}: {val}")
    price_cent = meta.get("avg_price_cent") or meta.get("price_cent")
    if price_cent is not None and price_cent != "":
        try:
            yuan = int(price_cent) / 100
            parts.append(f"人均(元): {yuan:g}")
        except (TypeError, ValueError):
            pass
    parts.append(f"内容: {chunk.content}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Simple RAG generator — drop-in replacement for GroundedRAGGenerator
# ---------------------------------------------------------------------------

NO_EVIDENCE_ANSWER = (
    "当前资料不足以给出可靠结论。你可以尝试扩大距离范围、提高预算上限，"
    "或换一个菜系、场景或时间条件。"
)


@dataclass(frozen=True, slots=True)
class RAGGeneration:
    answer: str
    sources: tuple[SourceCitation, ...]
    model_version: str | None = None
    fallback_reason: str | None = None


class SimpleRAGGenerator:
    """Lightweight RAG generator backed by LangChain + ChatOpenAI.

    Replaces the ~800-line GroundedRAGGenerator with a clean three-step flow:
    1. Format chunks → context string
    2. Call LLM via LangChainRAGAdapter
    3. Fall back to render_fallback() when LLM is unavailable
    """

    def __init__(self, model: LangChainRAGAdapter) -> None:
        self._model = model
        self._chain = _build_chain(
            model._api_key,
            model._api_base,
            model._model_name,
            model._temperature,
            model._max_tokens,
            model._timeout,
        )

    def generate(self, query: str, chunks: Sequence[RetrievedChunk]) -> RAGGeneration:
        """Run RAG and return a generation result."""
        citations = chunks_to_citations(chunks)

        if not chunks:
            return RAGGeneration(
                answer=NO_EVIDENCE_ANSWER, sources=(), fallback_reason="no_evidence"
            )

        # No API key → fall back to local results immediately
        if not self._model._api_key:
            return RAGGeneration(
                answer=render_fallback(chunks),
                sources=citations,
                model_version="local-fallback",
                fallback_reason="no_api_key",
            )

        context = chunks_to_context(chunks)

        if self._chain is not None:
            try:
                text = self._chain.invoke({"query": query, "context": context})
                if text and text.strip():
                    return RAGGeneration(
                        answer=text.strip(),
                        sources=citations,
                        model_version=self._model.version,
                    )
            except Exception:
                logger.warning("LLM generation failed, using local fallback", exc_info=True)

        # LLM unavailable → show raw search results
        return RAGGeneration(
            answer=render_fallback(chunks),
            sources=citations,
            model_version="local-fallback",
            fallback_reason="llm_unavailable",
        )
