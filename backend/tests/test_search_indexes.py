from unittest.mock import MagicMock

import pytest

from app.infrastructure.search.indexes import (
    chunk_index_body,
    create_chunk_index,
    ensure_chunk_index,
    switch_chunk_aliases,
)


def test_chunk_index_mapping_is_strict_and_dimensioned() -> None:
    body = chunk_index_body(512)

    assert body["settings"]["index.knn"] is True
    assert "zh_search" in body["settings"]["analysis"]["analyzer"]
    assert body["mappings"]["dynamic"] == "strict"
    properties = body["mappings"]["properties"]
    assert properties["content"]["analyzer"] == "zh_index"
    assert properties["content"]["search_analyzer"] == "zh_search"
    assert properties["content_vector"] == {
        "type": "knn_vector",
        "dimension": 512,
        "method": {
            "name": "hnsw",
            "space_type": "cosinesimil",
            "engine": "lucene",
        },
    }
    assert properties["tenant_id"] == {"type": "keyword"}
    assert properties["knowledge_base_id"] == {"type": "keyword"}
    assert properties["metadata"] == {"type": "object", "enabled": False}


def test_ensure_chunk_index_creates_version_and_runtime_aliases() -> None:
    client = MagicMock()
    client.indices.exists.return_value = False
    client.indices.exists_alias.return_value = False

    ensure_chunk_index(
        client,
        index="local-life-chunks-v1",
        read_alias="local-life-chunks-read",
        write_alias="local-life-chunks-write",
        embedding_dimension=512,
    )

    create = client.indices.create.call_args.kwargs
    assert create["index"] == "local-life-chunks-v1"
    assert create["body"]["mappings"]["dynamic"] == "strict"
    actions = client.indices.update_aliases.call_args.kwargs["body"]["actions"]
    assert actions == [
        {
            "add": {
                "index": "local-life-chunks-v1",
                "alias": "local-life-chunks-read",
            }
        },
        {
            "add": {
                "index": "local-life-chunks-v1",
                "alias": "local-life-chunks-write",
                "is_write_index": True,
            }
        },
    ]


def test_chunk_index_creation_falls_back_when_ik_plugin_is_unavailable() -> None:
    client = MagicMock()
    client.indices.create.side_effect = [RuntimeError("unknown ik_smart"), None]

    create_chunk_index(client, index="chunks-v2", embedding_dimension=512)

    calls = client.indices.create.call_args_list
    assert len(calls) == 2
    fallback = calls[1].kwargs["body"]
    assert fallback["mappings"]["properties"]["content"] == {
        "type": "text",
        "analyzer": "zh_search",
    }
    assert fallback["settings"]["analysis"]["analyzer"]["zh_search"]["tokenizer"] == ("standard")


def test_ensure_chunk_index_preserves_an_established_runtime_route() -> None:
    client = MagicMock()
    client.indices.exists.return_value = True
    client.indices.exists_alias.return_value = True
    client.indices.get_alias.side_effect = [
        {"local-life-chunks-v1": {}},
        {"local-life-chunks-v1": {}},
    ]

    ensure_chunk_index(
        client,
        index="local-life-chunks-v2",
        read_alias="local-life-chunks-read",
        write_alias="local-life-chunks-write",
        embedding_dimension=512,
    )

    client.indices.update_aliases.assert_not_called()


def test_ensure_chunk_index_rejects_inconsistent_runtime_aliases() -> None:
    client = MagicMock()
    client.indices.exists.return_value = True
    client.indices.exists_alias.return_value = True
    client.indices.get_alias.side_effect = [
        {"local-life-chunks-v2": {}},
        {"local-life-chunks-v1": {}},
    ]

    with pytest.raises(RuntimeError, match="read/write aliases"):
        ensure_chunk_index(
            client,
            index="local-life-chunks-v1",
            read_alias="local-life-chunks-read",
            write_alias="local-life-chunks-write",
            embedding_dimension=512,
        )

    client.indices.update_aliases.assert_not_called()


def test_switch_chunk_aliases_does_not_create_or_modify_index_mapping() -> None:
    client = MagicMock()
    client.indices.exists_alias.return_value = False

    switch_chunk_aliases(
        client,
        index="local-life-chunks-v2",
        read_alias="local-life-chunks-read",
        write_alias="local-life-chunks-write",
    )

    client.indices.create.assert_not_called()
    client.indices.put_mapping.assert_not_called()
    client.indices.update_aliases.assert_called_once()
