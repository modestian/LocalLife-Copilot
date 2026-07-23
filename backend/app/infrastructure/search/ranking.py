"""RRF/weighted fusion, optional reranking, diversity, and safe fallback."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from app.infrastructure.search.retrieval import DualRecallResult, RecallHit

FusionMethod = Literal["rrf", "weighted"]


class Reranker(Protocol):
    """Adapter contract for an optional cross-encoder reranker."""

    def score(self, query: str, hits: Sequence[RankedHit]) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class RankingConfig:
    method: FusionMethod = "rrf"
    rrf_k: int = 60
    bm25_weight: float = 0.5
    vector_weight: float = 0.5
    rerank_top_n: int = 20
    minimum_score: float = 0.0
    minimum_evidence: int = 1
    max_merchant_ratio: float = 0.4

    def __post_init__(self) -> None:
        if self.method not in ("rrf", "weighted"):
            raise ValueError("method must be 'rrf' or 'weighted'")
        if self.rrf_k <= 0 or self.rerank_top_n <= 0:
            raise ValueError("rrf_k and rerank_top_n must be positive")
        if min(self.bm25_weight, self.vector_weight) < 0:
            raise ValueError("fusion weights must not be negative")
        if self.bm25_weight + self.vector_weight <= 0:
            raise ValueError("at least one fusion weight must be positive")
        if not math.isfinite(self.minimum_score):
            raise ValueError("minimum_score must be finite")
        if self.minimum_evidence <= 0:
            raise ValueError("minimum_evidence must be positive")
        if not 0 < self.max_merchant_ratio <= 1:
            raise ValueError("max_merchant_ratio must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class RankedHit:
    document_id: str
    source: Mapping[str, Any]
    fused_score: float
    final_score: float
    recall_sources: tuple[str, ...]
    bm25_score: float | None = None
    vector_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class RankingResult:
    hits: tuple[RankedHit, ...]
    fallback: bool
    fallback_reason: str | None = None


def rank_recall(
    query: str,
    recalled: DualRecallResult,
    *,
    top_k: int,
    config: RankingConfig | None = None,
    reranker: Reranker | None = None,
    target_merchant_id: str | None = None,
) -> RankingResult:
    """Rank recalled evidence without directly comparing incompatible raw scores."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("search query must not be blank")
    selected_config = config or RankingConfig()
    hits = _fuse(recalled, selected_config)

    if reranker is not None and hits:
        head = hits[: selected_config.rerank_top_n]
        scores = tuple(reranker.score(normalized_query, head))
        if len(scores) != len(head) or any(not _is_finite_number(score) for score in scores):
            raise ValueError("reranker must return one finite score per hit")
        reranked = [
            replace(hit, rerank_score=float(score), final_score=float(score))
            for hit, score in zip(head, scores, strict=True)
        ]
        hits = sorted(reranked, key=_sort_key, reverse=True) + hits[len(head) :]

    diverse = _diversify(
        hits,
        top_k=top_k,
        max_ratio=selected_config.max_merchant_ratio,
        bypass=bool(target_merchant_id and target_merchant_id.strip()),
    )
    if len(diverse) < selected_config.minimum_evidence:
        return RankingResult((), True, "insufficient_evidence")
    if diverse[0].final_score < selected_config.minimum_score:
        return RankingResult((), True, "low_score")
    return RankingResult(tuple(diverse), False)


def _fuse(recalled: DualRecallResult, config: RankingConfig) -> list[RankedHit]:
    channels = {"bm25": recalled.bm25, "vector": recalled.vector}
    normalized = {name: _min_max_scores(hits) for name, hits in channels.items()}
    accumulated: dict[str, dict[str, Any]] = {}
    for channel, hits in channels.items():
        for rank, hit in enumerate(hits, start=1):
            item = accumulated.setdefault(
                hit.document_id,
                {"source": hit.source, "score": 0.0, "channels": [], "raw": {}},
            )
            item["channels"].append(channel)
            item["raw"][channel] = hit.score
            if config.method == "rrf":
                item["score"] += 1.0 / (config.rrf_k + rank)
            else:
                weight = config.bm25_weight if channel == "bm25" else config.vector_weight
                item["score"] += weight * normalized[channel][hit.document_id]

    result = [
        RankedHit(
            document_id=document_id,
            source=value["source"],
            fused_score=value["score"],
            final_score=value["score"],
            recall_sources=tuple(value["channels"]),
            bm25_score=value["raw"].get("bm25"),
            vector_score=value["raw"].get("vector"),
        )
        for document_id, value in accumulated.items()
    ]
    return sorted(result, key=_sort_key, reverse=True)


def _min_max_scores(hits: Sequence[RecallHit]) -> dict[str, float]:
    if not hits:
        return {}
    low = min(hit.score for hit in hits)
    high = max(hit.score for hit in hits)
    if high == low:
        return {hit.document_id: 1.0 for hit in hits}
    return {hit.document_id: (hit.score - low) / (high - low) for hit in hits}


def _diversify(
    hits: Sequence[RankedHit], *, top_k: int, max_ratio: float, bypass: bool
) -> list[RankedHit]:
    if bypass:
        return list(hits[:top_k])
    merchant_limit = max(1, math.floor(top_k * max_ratio))
    counts: Counter[str] = Counter()
    selected: list[RankedHit] = []
    for hit in hits:
        merchant_id = str(hit.source.get("merchant_id") or "").strip()
        if merchant_id and counts[merchant_id] >= merchant_limit:
            continue
        selected.append(hit)
        if merchant_id:
            counts[merchant_id] += 1
        if len(selected) == top_k:
            break
    return selected


def _is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


def _sort_key(hit: RankedHit) -> tuple[float, str]:
    return hit.final_score, hit.document_id
