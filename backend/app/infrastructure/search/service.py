"""Query embedding orchestration for hybrid recall."""

from datetime import datetime

from app.etl.embeddings import BatchedEmbedder
from app.infrastructure.search.retrieval import (
    DualRecallResult,
    OpenSearchDualRetriever,
    TrustedSearchScope,
)


class HybridRecallService:
    """Embed one normalized query and execute both OpenSearch recall paths."""

    def __init__(self, embedder: BatchedEmbedder, retriever: OpenSearchDualRetriever) -> None:
        self._embedder = embedder
        self._retriever = retriever

    def recall(
        self,
        query: str,
        scope: TrustedSearchScope,
        *,
        top_n: int = 50,
        now: datetime | None = None,
    ) -> DualRecallResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("search query must not be blank")
        vector = self._embedder.embed([normalized_query])[0]
        return self._retriever.recall(
            normalized_query,
            vector,
            scope,
            top_n=top_n,
            now=now,
        )
