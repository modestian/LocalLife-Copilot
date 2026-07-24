from collections.abc import Mapping
from typing import Any

from opensearchpy import OpenSearch


def chunk_index_body(embedding_dimension: int) -> dict[str, Any]:
    """Build the immutable settings and strict mapping for one Chunk index version.

    Uses ik_smart/ik_max_word for Chinese tokenization with standard fallback.
    """
    return {
        "settings": {
            "index.knn": True,
            "index.knn.algo_param.ef_search": 100,
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "zh_search": {
                        "type": "ik_smart",
                    },
                    "zh_index": {
                        "type": "ik_max_word",
                    },
                    "zh_standard": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    },
                }
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": {
                "chunk_id": {"type": "keyword"},
                "tenant_id": {"type": "keyword"},
                "knowledge_base_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "document_version_id": {"type": "keyword"},
                "merchant_id": {"type": "keyword"},
                "content": {
                    "type": "text",
                    "analyzer": "zh_index",
                    "search_analyzer": "zh_search",
                    "fields": {
                        "standard": {"type": "text", "analyzer": "zh_standard"},
                    },
                },
                "content_vector": {
                    "type": "knn_vector",
                    "dimension": embedding_dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
                "source_key": {"type": "keyword"},
                "source_type": {"type": "keyword"},
                "source_location": {"type": "keyword", "index": False},
                "category_ids": {"type": "keyword"},
                "price_cent": {"type": "long"},
                "location": {"type": "geo_point"},
                "business_status": {"type": "keyword"},
                "valid_from": {"type": "date"},
                "valid_to": {"type": "date"},
                "resource_scope": {"type": "keyword"},
                "chunk_no": {"type": "integer"},
                "content_hash": {"type": "keyword"},
                "token_count": {"type": "integer"},
                "page_number": {"type": "integer"},
                "metadata": {"type": "object", "dynamic": True},
                "updated_at": {"type": "date"},
            },
        },
    }


def ensure_chunk_index(
    client: OpenSearch,
    *,
    index: str,
    read_alias: str,
    write_alias: str,
    embedding_dimension: int,
) -> None:
    """Create the initial index without replacing an established runtime route."""
    if not client.indices.exists(index=index):
        body = chunk_index_body(embedding_dimension)
        try:
            client.indices.create(index=index, body=body)
        except Exception:
            # Fall back to standard analyzer if ik plugin is unavailable
            body["settings"]["analysis"]["analyzer"]["zh_search"] = {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase"],
            }
            body["settings"]["analysis"]["analyzer"]["zh_index"] = body["settings"]["analysis"][
                "analyzer"
            ]["zh_search"]
            body["mappings"]["properties"]["content"] = {
                "type": "text",
                "analyzer": "zh_search",
            }
            client.indices.create(index=index, body=body)

    read_indexes = _alias_indexes(client, read_alias)
    write_indexes = _alias_indexes(client, write_alias)
    if not read_indexes and not write_indexes:
        switch_chunk_aliases(
            client,
            index=index,
            read_alias=read_alias,
            write_alias=write_alias,
        )
        return
    if read_indexes != write_indexes:
        raise RuntimeError("OpenSearch read/write aliases point to different indexes")


def switch_chunk_aliases(
    client: OpenSearch,
    *,
    index: str,
    read_alias: str,
    write_alias: str,
) -> None:
    """Atomically move the read and write aliases to one populated index version."""

    actions: list[dict[str, dict[str, object]]] = []
    for alias in (read_alias, write_alias):
        for previous_index in _alias_indexes(client, alias):
            if previous_index != index:
                actions.append({"remove": {"index": previous_index, "alias": alias}})

    actions.extend(
        [
            {"add": {"index": index, "alias": read_alias}},
            {
                "add": {
                    "index": index,
                    "alias": write_alias,
                    "is_write_index": True,
                }
            },
        ]
    )
    client.indices.update_aliases(body={"actions": actions})


def _alias_indexes(client: OpenSearch, alias: str) -> set[str]:
    if not client.indices.exists_alias(name=alias):
        return set()
    response: Mapping[str, object] = client.indices.get_alias(name=alias)
    return set(response)
