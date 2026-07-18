from unittest.mock import MagicMock

import pytest

from app.infrastructure.search.ranking import RankingConfig, rank_recall
from app.infrastructure.search.retrieval import DualRecallResult, RecallHit


def hit(document_id: str, score: float, merchant: str) -> RecallHit:
    return RecallHit(document_id, score, {"merchant_id": merchant, "content": document_id})


def recalled() -> DualRecallResult:
    return DualRecallResult(
        bm25=(hit("a1", 100, "a"), hit("b1", 20, "b"), hit("a2", 10, "a")),
        vector=(hit("b1", 0.99, "b"), hit("c1", 0.8, "c"), hit("a1", 0.7, "a")),
    )


def test_rrf_rewards_documents_recalled_by_both_channels() -> None:
    result = rank_recall("咖啡", recalled(), top_k=3)
    assert not result.fallback
    assert result.hits[0].document_id in {"a1", "b1"}
    assert result.hits[0].recall_sources == ("bm25", "vector")
    assert result.hits[0].bm25_score is not None
    assert result.hits[0].vector_score is not None


def test_weighted_fusion_normalizes_each_channel_before_combining() -> None:
    result = rank_recall(
        "咖啡",
        recalled(),
        top_k=3,
        config=RankingConfig(method="weighted", bm25_weight=0.2, vector_weight=0.8),
    )
    assert result.hits[0].document_id == "b1"


def test_optional_reranker_only_scores_configured_head() -> None:
    reranker = MagicMock()
    reranker.score.return_value = [0.1, 0.9]
    result = rank_recall(
        "咖啡",
        recalled(),
        top_k=2,
        config=RankingConfig(rerank_top_n=2),
        reranker=reranker,
    )
    assert len(reranker.score.call_args.args[1]) == 2
    assert result.hits[0].rerank_score == 0.9


def test_diversity_caps_one_merchant_at_40_percent() -> None:
    data = DualRecallResult(
        bm25=tuple(hit(f"a{i}", 10 - i, "a") for i in range(5))
        + tuple(hit(f"b{i}", 5 - i, f"b{i}") for i in range(5)),
        vector=(),
    )
    result = rank_recall("咖啡", data, top_k=5)
    assert sum(item.source["merchant_id"] == "a" for item in result.hits) == 2
    assert len(result.hits) == 5


def test_explicit_merchant_query_bypasses_diversity_cap() -> None:
    data = DualRecallResult(bm25=tuple(hit(f"a{i}", 10 - i, "a") for i in range(5)), vector=())
    assert len(rank_recall("这家店", data, top_k=5, target_merchant_id="a").hits) == 5


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        (RankingConfig(minimum_evidence=5), "insufficient_evidence"),
        (RankingConfig(minimum_score=1.0), "low_score"),
    ],
)
def test_low_quality_results_return_empty_with_fallback_marker(config, reason) -> None:
    result = rank_recall("咖啡", recalled(), top_k=3, config=config)
    assert result.hits == ()
    assert result.fallback
    assert result.fallback_reason == reason


@pytest.mark.parametrize("scores", [[0.5], [float("nan"), 0.2], [True, 0.2]])
def test_invalid_reranker_output_is_rejected(scores) -> None:
    reranker = MagicMock()
    reranker.score.return_value = scores
    with pytest.raises(ValueError, match="one finite score"):
        rank_recall("咖啡", recalled(), top_k=3, reranker=reranker)
