from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.infrastructure.search.retrieval import TrustedSearchScope
from app.infrastructure.search.service import HybridRecallService


def test_hybrid_recall_embeds_normalized_query_once_and_forwards_trusted_scope() -> None:
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    retriever = MagicMock()
    expected = object()
    retriever.recall.return_value = expected
    scope = TrustedSearchScope(
        tenant_id="tenant-1",
        knowledge_base_ids=frozenset({"kb-1"}),
        resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
    )
    now = datetime(2026, 7, 18, tzinfo=UTC)

    result = HybridRecallService(embedder, retriever).recall(
        "  安静的咖啡馆  ", scope, top_n=25, now=now
    )

    assert result is expected
    embedder.embed.assert_called_once_with(["安静的咖啡馆"])
    retriever.recall.assert_called_once_with("安静的咖啡馆", [0.1, 0.2], scope, top_n=25, now=now)
