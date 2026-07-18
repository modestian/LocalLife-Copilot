from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.infrastructure.search.pipeline import HybridSearchService
from app.infrastructure.search.ranking import RankingConfig
from app.infrastructure.search.retrieval import DualRecallResult, RecallHit, TrustedSearchScope


def test_pipeline_forwards_trusted_scope_and_ranks_dual_recall() -> None:
    recall_service = MagicMock()
    recall_service.recall.return_value = DualRecallResult(
        bm25=(RecallHit("a", 3.0, {"merchant_id": "m1"}),),
        vector=(RecallHit("b", 0.8, {"merchant_id": "m2"}),),
    )
    scope = TrustedSearchScope(
        tenant_id="tenant-1",
        knowledge_base_ids=frozenset({"kb-1"}),
        resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
    )
    now = datetime(2026, 7, 18, tzinfo=UTC)

    result = HybridSearchService(
        recall_service,
        config=RankingConfig(minimum_evidence=2),
    ).search(" 咖啡 ", scope, top_k=5, recall_top_n=30, now=now)

    recall_service.recall.assert_called_once_with(" 咖啡 ", scope, top_n=30, now=now)
    assert not result.fallback
    assert {item.document_id for item in result.hits} == {"a", "b"}
