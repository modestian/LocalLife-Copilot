"""OpenSearch 3.x compatible TK-202-06 benchmark entry point."""

from __future__ import annotations

import hashlib
from typing import Any

import evaluate_search
from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

from app.etl.embeddings import BatchedEmbedder
from app.infrastructure.search.indexes import chunk_index_body


def prepare_index(
    client: OpenSearch,
    *,
    index: str,
    dataset: dict[str, Any],
    dataset_sha256: str,
    embedder: BatchedEmbedder,
    dimension: int,
) -> None:
    """Keep the frozen dataset checksum in mapping metadata supported by OpenSearch 3.x."""
    if not client.indices.exists(index=index):
        body = chunk_index_body(dimension)
        body["mappings"]["_meta"] = {"evaluation_dataset_sha256": dataset_sha256}
        client.indices.create(index=index, body=body)
    mapping = client.indices.get_mapping(index=index)[index]["mappings"]
    if mapping.get("_meta", {}).get("evaluation_dataset_sha256") != dataset_sha256:
        raise RuntimeError(f"isolated index {index!r} belongs to a different dataset")

    documents = dataset["documents"]
    vectors = embedder.embed([document["content"] for document in documents])
    scope = dataset["scope"]
    actions = []
    for document, vector in zip(documents, vectors, strict=True):
        merchant_id = document["merchant_id"]
        content = document["content"]
        actions.append(
            {
                "_op_type": "index",
                "_index": index,
                "_id": f"{dataset['dataset_version']}:{merchant_id}",
                "_source": {
                    "chunk_id": f"chunk-{merchant_id}",
                    "document_id": f"document-{merchant_id}",
                    "document_version_id": f"version-{merchant_id}",
                    "tenant_id": scope["tenant_id"],
                    "knowledge_base_id": scope["knowledge_base_id"],
                    "merchant_id": merchant_id,
                    "content": content,
                    "content_vector": vector,
                    "source_key": "search_benchmark_v1.json",
                    "source_type": "merchant",
                    "source_location": f"TK-202-06/{merchant_id}",
                    "category_ids": document["category_ids"],
                    "price_cent": document["price_cent"],
                    "business_status": "OPEN",
                    "resource_scope": [f"KNOWLEDGE_BASE:{scope['knowledge_base_id']}"],
                    "chunk_no": 0,
                    "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                    "token_count": len(content),
                    "metadata": {"benchmark": dataset["dataset_version"]},
                    "updated_at": "2026-07-19T00:00:00Z",
                },
            }
        )
    bulk(client, actions, refresh="wait_for")
    if client.count(index=index)["count"] != len(documents):
        raise RuntimeError("isolated evaluation index contains unexpected documents")


if __name__ == "__main__":
    evaluate_search.prepare_index = prepare_index
    raise SystemExit(evaluate_search.main())
