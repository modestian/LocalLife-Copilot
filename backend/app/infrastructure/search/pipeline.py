"""End-to-end hybrid recall and ranking orchestration."""

from datetime import datetime

from app.infrastructure.search.ranking import (
    RankingConfig,
    RankingResult,
    Reranker,
    rank_recall,
)
from app.infrastructure.search.retrieval import TrustedSearchScope
from app.infrastructure.search.service import HybridRecallService


class HybridSearchService:
    """Compose permission-safe recall with the TK-202-04 ranking stages."""

    def __init__(
        self,
        recall_service: HybridRecallService,
        *,
        config: RankingConfig | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._recall_service = recall_service
        self._config = config or RankingConfig()
        self._reranker = reranker

    def search(
        self,
        query: str,
        scope: TrustedSearchScope,
        *,
        top_k: int = 5,
        recall_top_n: int = 50,
        target_merchant_id: str | None = None,
        now: datetime | None = None,
    ) -> RankingResult:
        recalled = self._recall_service.recall(
            query,
            scope,
            top_n=recall_top_n,
            now=now,
        )
        return rank_recall(
            query,
            recalled,
            top_k=top_k,
            config=self._config,
            reranker=self._reranker,
            target_merchant_id=target_merchant_id,
        )
