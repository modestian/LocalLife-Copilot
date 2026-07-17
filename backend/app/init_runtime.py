from opensearchpy import OpenSearch

from app.core.config import get_settings


def main() -> None:
    """Create the development search index once; safe to run repeatedly."""
    settings = get_settings()
    client = OpenSearch(settings.opensearch_url)
    mappings = {
        "properties": {
            "content": {"type": "text"},
            "source_key": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "document_version_id": {"type": "keyword"},
            "knowledge_base_id": {"type": "keyword"},
            "merchant_id": {"type": "keyword"},
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
        }
    }
    try:
        if client.indices.exists(index=settings.opensearch_index):
            client.indices.put_mapping(index=settings.opensearch_index, body=mappings)
            return
        client.indices.create(
            index=settings.opensearch_index,
            body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
                "mappings": mappings,
            },
        )
    finally:
        client.close()


if __name__ == "__main__":
    main()
